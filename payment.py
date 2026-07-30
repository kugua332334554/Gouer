import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid

import httpx

import config
import database

logger = logging.getLogger(__name__)

EMOJI_BUY = "6044023213250319833"
EMOJI_CROWN = "5805337324967432449"
EMOJI_DIAMOND = "5332814802702056788"
EMOJI_CHECK = "5870984877884576308"
EMOJI_STAR = "5208801655004350721"
EMOJI_MONEY = "5436386989857320953"

SECRET_BYTES = config.MYQB_SECRET.encode() if config.MYQB_SECRET else b""
APP_ID = config.MYQB_APP_ID
BASE_URL = config.MYQB_BASE_URL.rstrip("/") if config.MYQB_BASE_URL else ""

# ── 签名 ──────────────────────────────────────────

def _sign(method: str, path: str, body: str, ts: str, nonce: str) -> str:
    message = f"{method}\n{path}\n{body}\n{ts}\n{nonce}".encode()
    return hmac.new(SECRET_BYTES, message, hashlib.sha256).hexdigest()


def _build_headers(method: str, path: str, body: str) -> dict:
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    sig = _sign(method, path, body, ts, nonce)
    return {
        "X-App-Id": APP_ID,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": sig,
        "Content-Type": "application/json",
    }


# ── API 调用 ──────────────────────────────────────


async def _call(method: str, path: str, body: dict | None = None) -> dict:
    """调用 MYQB API，返回响应 JSON dict。"""
    body_str = json.dumps(body, separators=(",", ":")) if body else ""
    headers = _build_headers(method, path, body_str)
    url = f"{BASE_URL}{path}"

    async with httpx.AsyncClient(timeout=15) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        else:
            resp = await client.post(url, content=body_str.encode(), headers=headers)
        return resp.json()


async def create_order(merchant_order_no: str, currency: str, amount: str, attach: str = "") -> dict:
    if not APP_ID or not SECRET_BYTES:
        logger.warning(f"create_order: MYQB not configured, APP_ID={APP_ID!r}, SECRET_BYTES={bool(SECRET_BYTES)}")
        return {"ok": False, "error": "MYQB 未配置 (APP_ID/SECRET 缺失)"}
    logger.info(f"create_order: calling MYQB, order_no={merchant_order_no}, currency={currency}, amount={amount}")

    body = {
        "merchant_order_no": merchant_order_no,
        "currency": currency,
        "amount": amount,
    }
    if attach:
        body["attach"] = attach

    try:
        resp = await _call("POST", "/api/v1/orders", body)
        if resp.get("code") == 0:
            data = resp.get("data", {})
            return {
                "ok": True,
                "merchant_order_no": data.get("merchant_order_no", merchant_order_no),
                "order_id": data.get("order_id"),
                "pay_url": data.get("pay_url", ""),
                "expires_at": data.get("expires_at"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
            }
        return {"ok": False, "error": resp.get("message", "未知错误"), "code": resp.get("code")}
    except Exception as e:
        logger.error(f"create_order failed: {e}")
        return {"ok": False, "error": str(e)}


async def query_order(merchant_order_no: str) -> dict:
    """查询收款单状态。返回 {"ok": True/False, "status": "created"|"paid"|"expired", ...}"""
    if not APP_ID or not SECRET_BYTES:
        return {"ok": False, "error": "MYQB 未配置"}

    try:
        resp = await _call("GET", f"/api/v1/orders/{merchant_order_no}")
        if resp.get("code") == 0:
            data = resp.get("data", {})
            return {"ok": True, "status": data.get("status"), **data}
        return {"ok": False, "error": resp.get("message", "未知错误"), "code": resp.get("code")}
    except Exception as e:
        logger.error(f"query_order failed: {e}")
        return {"ok": False, "error": str(e)}


# ── 轮询 ──────────────────────────────────────────
_PAID_STATUSES = {"paid", "notifying", "notified", "notify_failed"}


async def poll_order(bot, chat_id: int, user_id: int, merchant_order_no: str,
                     feature: str, timeout: int = 600, interval: int = 5):
    deadline = time.monotonic() + timeout
    last_status = None

    while time.monotonic() < deadline:
        await asyncio.sleep(interval)

        result = await query_order(merchant_order_no)
        if not result.get("ok"):
            continue

        status = result.get("status", "")
        if status != last_status:
            logger.info(f"poll_order {merchant_order_no}: status={status}")
            last_status = status

        # 支付成功 → 激活订阅
        if status in _PAID_STATUSES:
            await database.update_payment_order(merchant_order_no, "paid")
            await database.activate_subscription(chat_id, feature)
            try:
                from datetime import datetime, timedelta
                exp = datetime.now() + timedelta(days=30)
                fname = _feature_name(feature)
                # 通知发到付款用户的私聊，不要发到群里
                await bot.send_message(
                    chat_id=user_id,
                    text=f'<tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> <b>支付成功！</b>\n\n'
                         f'<tg-emoji emoji-id="{EMOJI_CROWN}">👑</tg-emoji> {fname}订阅已激活\n'
                         f'<tg-emoji emoji-id="{EMOJI_STAR}">🌟</tg-emoji> 有效期至 {exp.strftime("%Y-%m-%d")}\n\n'
                         f'群组 <code>{chat_id}</code> 的订阅已生效。',
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"notify paid failed: {e}")
            return

        # 订单过期
        if status == "expired":
            await database.update_payment_order(merchant_order_no, "expired")
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f'<tg-emoji emoji-id="{EMOJI_MONEY}">🤑</tg-emoji> <b>订单已过期</b>\n\n'
                         f'如需继续，请重新发起购买。',
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return

    # 超时
    await database.update_payment_order(merchant_order_no, "timeout")
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f'<tg-emoji emoji-id="{EMOJI_MONEY}">🤑</tg-emoji> <b>支付超时</b>（{timeout // 60}分钟）\n\n'
                 f'如需继续，请重新发起购买。',
            parse_mode="HTML"
        )
    except Exception:
        pass
    logger.info(f"poll_order {merchant_order_no}: timeout after {timeout}s")


def _feature_name(feature: str) -> str:
    return "AI" if feature == "ai" else "名片"
