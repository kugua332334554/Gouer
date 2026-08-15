import asyncio
import logging
import re
from datetime import datetime
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

# TRON 主网 USDT (TRC20) 合约地址
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# 公开 Tronscan API
_ACCOUNT_URL = "https://apilist.tronscanapi.com/api/account"
_TRANSFERS_URL = "https://apilist.tronscanapi.com/api/token_trc20/transfers"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# TRON 地址：T 开头 + 33 位 Base58 字符，共 34 位
_ADDR_RE = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")

_DEFAULT_LIMIT = 5


def _find_tron_addresses(text: str) -> list:
    """从消息中提取所有 TRON 地址（去重）。"""
    return list(dict.fromkeys(_ADDR_RE.findall(text)))


async def _fetch_account(address: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_ACCOUNT_URL, params={"address": address}, headers=_HEADERS)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"addr fetch account err: {e}")
        return {}


def _extract_trx_balance(acct: dict):
    """TRX 余额，acct['balance'] 单位是 sun。返回 (raw_sun, formatted_trx)。"""
    raw = acct.get("balance")
    if raw is None:
        return None
    try:
        raw = int(raw)
    except (TypeError, ValueError):
        return None
    return raw, f"{raw / 1_000_000:,.6f}"


def _extract_usdt_balance(acct: dict):
    """从 trc20token_balances 里找 USDT，返回 (raw, amount) 或 None。"""
    tokens = acct.get("trc20token_balances") or []
    for t in tokens:
        if t.get("tokenAbbr") == "USDT" and t.get("tokenId") == USDT_CONTRACT:
            return t.get("balance"), t.get("amount")
    return None


async def _fetch_usdt_transfers(address: str, limit: int = _DEFAULT_LIMIT) -> list:
    try:
        params = {
            "limit": limit,
            "start": 0,
            "relatedAddress": address,
            "contract_address": USDT_CONTRACT,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_TRANSFERS_URL, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"addr fetch transfers err: {e}")
        return []
    return data.get("token_transfers") or []


def _fmt_amount(raw, decimal: int):
    """把原始整数量按小数位换算成字符串，保留最多 6 位小数。"""
    try:
        raw = int(raw)
    except (TypeError, ValueError):
        return "0"
    value = raw / (10 ** decimal)
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _fmt_time(block_ts) -> str:
    try:
        ts = int(block_ts)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")


async def build_addr_report(address: str) -> str:
    """拼装地址报告：TRX 余额 + USDT 余额 + 最近 USDT 转账。"""
    acct = await _fetch_account(address)
    if not acct or "balance" not in acct:
        return f"⚠️ 地址 <code>{address}</code> 查询失败，请稍后再试。"

    lines = [f"<b>TRON 地址查询</b>\n<code>{address}</code>\n"]

    trx = _extract_trx_balance(acct)
    if trx:
        lines.append(f"TRX 余额：<b>{trx[1]}</b> TRX")
    else:
        lines.append("TRX 余额：0 TRX")

    usdt = _extract_usdt_balance(acct)
    if usdt:
        amount = usdt[1] if usdt[1] is not None else _fmt_amount(usdt[0] or 0, 6)
        lines.append(f"USDT 余额：<b>{amount}</b> USDT")
    else:
        lines.append("USDT 余额：0 USDT")

    transfers = await _fetch_usdt_transfers(address)
    if transfers:
        lines.append(f"\n<b>最近 {len(transfers)} 条 USDT 转账：</b>")
        for t in transfers:
            ti = t.get("tokenInfo") or {}
            decimal = ti.get("tokenDecimal", 6)
            amount = _fmt_amount(t.get("quant"), decimal)
            frm = t.get("from_address") or ""
            to = t.get("to_address") or ""
            short_from = (frm[:6] + "..." + frm[-4:]) if len(frm) > 12 else frm
            short_to = (to[:6] + "..." + to[-4:]) if len(to) > 12 else to
            direction = "收" if to == address else "发"
            lines.append(
                f"{direction} {amount} USDT · {short_from} → {short_to} · {_fmt_time(t.get('block_ts'))}"
            )
    else:
        lines.append("\n暂无 USDT 转账记录。")

    return "\n".join(lines)


async def addr_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """识别群消息中的 TRON 地址，自动查询余额和交易记录。"""
    msg = update.message
    if not msg or not msg.text:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    user = update.effective_user
    if not user or user.is_bot:
        return False

    addresses = _find_tron_addresses(msg.text)
    if not addresses:
        return False

    settings = await database.get_addr_settings(chat.id)
    if not settings["enabled"]:
        return False

    for address in addresses:
        report = await build_addr_report(address)
        try:
            sent = await context.bot.send_message(
                chat_id=chat.id, text=report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"addr send report err: {e}")
            continue
        delete_seconds = settings.get("delete_seconds") or 0
        if delete_seconds > 0:
            asyncio.create_task(_delayed_delete(context, chat.id, sent.message_id, delete_seconds))
    return True


async def _delayed_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"addr delayed delete err: {e}")


# ── 群管理面板：开关 + 定时删除 ──────────────────────────

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
ADDR_EMOJI_ID = "5875506366050734240"

_AWAIT_ADDR = {}


def get_addr_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    status_icon = CHECK_EMOJI_ID if s["enabled"] else CROSS_EMOJI_ID
    status_text = "开启" if s["enabled"] else "关闭"
    del_text = "不删除" if not s["delete_seconds"] else f'{s["delete_seconds"]} 秒'
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f'状态: {status_text}', callback_data=f"addr_toggle_{chat_id}", icon_custom_emoji_id=status_icon)],
        [InlineKeyboardButton(f'定时删除: {del_text}', callback_data=f"addr_duration_{chat_id}")],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")],
    ])


async def addr_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    try:
        parts = data.split("_")
        chat_id = None
        for cand in (parts[-1], parts[-2]):
            if cand.lstrip("-").isdigit():
                chat_id = int(cand)
                break
        if chat_id is None:
            return
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("addr_panel_"):
        await query.answer()
        s = await database.get_addr_settings(chat_id)
        del_text = "不删除" if not s["delete_seconds"] else f'{s["delete_seconds"]} 秒'
        text = (
            f'<tg-emoji emoji-id="{ADDR_EMOJI_ID}">🔍</tg-emoji> <b>地址识别查询</b>\n\n'
            f'开启后，识别群消息中的 TRON 地址，自动查询 TRX / USDT 余额及最近 USDT 转账。\n\n'
            f'<b>状态:</b> {"开启" if s["enabled"] else "关闭"}\n'
            f'<b>定时删除:</b> {del_text}'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_addr_keyboard(str(chat_id), s))
        return

    if data.startswith("addr_toggle_"):
        s = await database.get_addr_settings(chat_id)
        new_val = not s["enabled"]
        await database.update_addr_settings(chat_id, enabled=new_val)
        await query.answer(f'地址识别: {"开启" if new_val else "关闭"}')
        s = await database.get_addr_settings(chat_id)
        del_text = "不删除" if not s["delete_seconds"] else f'{s["delete_seconds"]} 秒'
        text = (
            f'<tg-emoji emoji-id="{ADDR_EMOJI_ID}">🔍</tg-emoji> <b>地址识别查询</b>\n\n'
            f'<b>状态:</b> {"开启" if s["enabled"] else "关闭"}\n'
            f'<b>定时删除:</b> {del_text}'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_addr_keyboard(str(chat_id), s))
        return

    if data.startswith("addr_duration_"):
        await query.answer()
        _AWAIT_ADDR[user_id] = chat_id
        _AWAIT_ADDR[f"{user_id}_conv"] = update.effective_chat.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"addr_panel_{chat_id}")]])
        await query.message.reply_html("请发送定时删除时间（秒，0 = 不删除）：", reply_markup=kb)
        return


async def addr_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conv = _AWAIT_ADDR.get(f"{user_id}_conv")
    if conv is not None and (update.effective_chat is None or update.effective_chat.id != conv):
        return
    chat_id = _AWAIT_ADDR.pop(user_id, None)
    _AWAIT_ADDR.pop(f"{user_id}_conv", None)
    if not chat_id:
        return

    msg = update.message
    if not msg or not msg.text:
        return
    raw = msg.text.strip()
    try:
        secs = int(raw)
        if secs < 0:
            raise ValueError
        await database.update_addr_settings(chat_id, delete_seconds=secs)
        if secs == 0:
            await msg.reply_html('<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji> 定时删除已关闭（不删除）')
        else:
            await msg.reply_html(f'<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji> 定时删除已设为 {secs} 秒')
    except Exception:
        await msg.reply_html('<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> 请输入有效秒数（≥0）')
