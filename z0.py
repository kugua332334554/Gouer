import asyncio
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

# OKX 网页端 C2C OTC 报价接口（公开，随时可能变动）
_OKX_BOOKS_URL = "https://www.okx.com/v3/c2c/tradingOrders/books"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# 拉取多少条卖单报价
_DEFAULT_LIMIT = 10


async def fetch_usdt_cny_sell_quotes(limit: int = _DEFAULT_LIMIT) -> list:
    """从欧易 C2C 拉取「商家卖 USDT / 收人民币 / 支付宝」的实时报价。

    返回按价格升序排列的商家列表 [{price, nick_name}, ...]；失败返回空列表。
    """
    params = {
        "side": "sell",                 # 商家卖 USDT（买家视角：用人民币买 USDT）
        "baseCurrency": "usdt",
        "quoteCurrency": "cny",
        "paymentMethod": "alipay",
        "userType": "all",
        "showTrade": "false",
        "showFollow": "false",
        "showAlreadyTraded": "false",
        "isAbleFilter": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_OKX_BOOKS_URL, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"z0 fetch okx quotes err: {e}")
        return []

    if data.get("code") != 0:
        logger.error(f"z0 okx api error: {data.get('error_message') or data.get('msg')}")
        return []

    sell = data.get("data", {}).get("sell") or []
    quotes = []
    for ad in sell:
        price = ad.get("price")
        nick = ad.get("nickName")
        if not price or not nick:
            continue
        quotes.append({"price": price, "nick_name": nick})

    quotes.sort(key=lambda q: float(q["price"]))
    return quotes[:limit]


async def send_z0_quotes(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """拉取并发送欧易 OTC 支付宝卖单汇率列表。"""
    quotes = await fetch_usdt_cny_sell_quotes()
    if not quotes:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ 获取欧易 OTC 实时报价失败，请稍后再试。",
            )
        except Exception as e:
            logger.error(f"z0 send error msg err: {e}")
        return None

    lines = ["<b>欧易 OTC 实时报价 - 支付宝</b>\n"]
    for q in quotes:
        lines.append(f"{q['price']}    {q['nick_name']}")
    text = "\n".join(lines)

    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return msg
    except Exception as e:
        logger.error(f"z0 send quotes err: {e}")
        return None


async def z0_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """群消息精确匹配 z0 时，返回欧易 OTC 支付宝卖单汇率列表。"""
    msg = update.message
    if not msg or not msg.text:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    user = update.effective_user
    if not user or user.is_bot:
        return False

    text = msg.text.strip()
    if text.lower() != "z0":
        return False

    settings = await database.get_z0_settings(chat.id)
    if not settings["enabled"]:
        return False

    sent = await send_z0_quotes(context, chat.id)
    if sent is None:
        return True  # 已响应（含失败提示），阻断后续模块

    delete_seconds = settings.get("delete_seconds") or 0
    if delete_seconds > 0:
        asyncio.create_task(_delayed_delete(context, chat.id, sent.message_id, delete_seconds))
    return True


async def _delayed_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"z0 delayed delete err: {e}")


# ── 群管理面板：开关 + 定时删除 ──────────────────────────

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
Z0_EMOJI_ID = "5875506366050734240"

_AWAIT_Z0 = {}


def get_z0_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    status_icon = CHECK_EMOJI_ID if s["enabled"] else CROSS_EMOJI_ID
    status_text = "开启" if s["enabled"] else "关闭"
    del_text = "不删除" if not s["delete_seconds"] else f'{s["delete_seconds"]} 秒'
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f'状态: {status_text}', callback_data=f"z0_toggle_{chat_id}", icon_custom_emoji_id=status_icon)],
        [InlineKeyboardButton(f'定时删除: {del_text}', callback_data=f"z0_duration_{chat_id}")],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")],
    ])


async def z0_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if data.startswith("z0_panel_"):
        await query.answer()
        s = await database.get_z0_settings(chat_id)
        del_text = "不删除" if not s["delete_seconds"] else f'{s["delete_seconds"]} 秒'
        text = (
            f'<tg-emoji emoji-id="{Z0_EMOJI_ID}">💱</tg-emoji> <b>Z0 汇率报价</b>\n\n'
            f'开启后，群里发送 <code>z0</code> 返回欧易 OTC 支付宝实时卖单汇率。\n\n'
            f'<b>状态:</b> {"开启" if s["enabled"] else "关闭"}\n'
            f'<b>定时删除:</b> {del_text}'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_z0_keyboard(str(chat_id), s))
        return

    if data.startswith("z0_toggle_"):
        s = await database.get_z0_settings(chat_id)
        new_val = not s["enabled"]
        await database.update_z0_settings(chat_id, enabled=new_val)
        await query.answer(f'Z0 汇率: {"开启" if new_val else "关闭"}')
        s = await database.get_z0_settings(chat_id)
        del_text = "不删除" if not s["delete_seconds"] else f'{s["delete_seconds"]} 秒'
        text = (
            f'<tg-emoji emoji-id="{Z0_EMOJI_ID}">💱</tg-emoji> <b>Z0 汇率报价</b>\n\n'
            f'<b>状态:</b> {"开启" if s["enabled"] else "关闭"}\n'
            f'<b>定时删除:</b> {del_text}'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_z0_keyboard(str(chat_id), s))
        return

    if data.startswith("z0_duration_"):
        await query.answer()
        _AWAIT_Z0[user_id] = chat_id
        _AWAIT_Z0[f"{user_id}_conv"] = update.effective_chat.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"z0_panel_{chat_id}")]])
        await query.message.reply_html("请发送定时删除时间（秒，0 = 不删除）：", reply_markup=kb)
        return


async def z0_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conv = _AWAIT_Z0.get(f"{user_id}_conv")
    if conv is not None and (update.effective_chat is None or update.effective_chat.id != conv):
        return
    chat_id = _AWAIT_Z0.pop(user_id, None)
    _AWAIT_Z0.pop(f"{user_id}_conv", None)
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
        await database.update_z0_settings(chat_id, delete_seconds=secs)
        if secs == 0:
            await msg.reply_html('<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji> 定时删除已关闭（不删除）')
        else:
            await msg.reply_html(f'<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji> 定时删除已设为 {secs} 秒')
    except Exception:
        await msg.reply_html('<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> 请输入有效秒数（≥0）')
