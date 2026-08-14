import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)
logger.info("media_autodelete module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
TRASH_EMOJI_ID = "5879937509579820068"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

# 需要定时删除的媒体消息类型
MEDIA_FIELDS = ("photo", "video", "document", "audio", "voice", "animation", "sticker", "video_note")

_AWAIT_MEDIA = {}


def is_media_message(msg) -> bool:
    """判断消息是否包含媒体(图片/视频/文件/音频/语音/GIF/贴纸/视频备注)。"""
    return any(getattr(msg, f, None) for f in MEDIA_FIELDS)


async def get_media_autodelete_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    status_icon = CHECK_EMOJI_ID if s["enabled"] else CROSS_EMOJI_ID
    status_text = "开启" if s["enabled"] else "关闭"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f'状态: {status_text}', callback_data=f"mad_toggle_{chat_id}", icon_custom_emoji_id=status_icon)],
        [InlineKeyboardButton(f'删除时间: {s["delete_minutes"]}分钟', callback_data=f"mad_duration_{chat_id}")],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")],
    ])
    return kb


async def media_autodelete_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if data.startswith("mad_panel_"):
        await query.answer()
        s = await database.get_media_autodelete_settings(chat_id)
        text = (
            f'<tg-emoji emoji-id="{TRASH_EMOJI_ID}">🗑</tg-emoji> <b>媒体定时删除</b>\n\n'
            f'开启后，群内媒体消息(图片/视频/文件/音频/GIF/贴纸等)将在指定时间后自动删除。\n\n'
            f'<b>状态:</b> {"开启" if s["enabled"] else "关闭"}\n'
            f'<b>删除时间:</b> {s["delete_minutes"]} 分钟'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=await get_media_autodelete_keyboard(str(chat_id), s))
        return

    if data.startswith("mad_toggle_"):
        s = await database.get_media_autodelete_settings(chat_id)
        new_val = not s["enabled"]
        await database.update_media_autodelete_settings(chat_id, enabled=new_val)
        await query.answer(f'媒体定时删除: {"开启" if new_val else "关闭"}')
        s = await database.get_media_autodelete_settings(chat_id)
        text = (
            f'<tg-emoji emoji-id="{TRASH_EMOJI_ID}">🗑</tg-emoji> <b>媒体定时删除</b>\n\n'
            f'<b>状态:</b> {"开启" if s["enabled"] else "关闭"}\n'
            f'<b>删除时间:</b> {s["delete_minutes"]} 分钟'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=await get_media_autodelete_keyboard(str(chat_id), s))
        return

    if data.startswith("mad_duration_"):
        await query.answer()
        _AWAIT_MEDIA[user_id] = chat_id
        _AWAIT_MEDIA[f"{user_id}_conv"] = update.effective_chat.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"mad_panel_{chat_id}")]])
        await query.message.reply_html("请发送删除时间（分钟）：", reply_markup=kb)
        return


async def media_autodelete_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conv = _AWAIT_MEDIA.get(f"{user_id}_conv")
    if conv is not None and (update.effective_chat is None or update.effective_chat.id != conv):
        return
    chat_id = _AWAIT_MEDIA.pop(user_id, None)
    _AWAIT_MEDIA.pop(f"{user_id}_conv", None)
    if not chat_id:
        return

    msg = update.message
    if not msg or not msg.text:
        return
    raw = msg.text.strip()
    try:
        mins = int(raw)
        if mins < 1:
            raise ValueError
        await database.update_media_autodelete_settings(chat_id, delete_minutes=mins)
        await msg.reply_html(f"{EMOJI_SUCCESS} 删除时间已设为 {mins} 分钟")
    except Exception:
        await msg.reply_html('<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> 请输入有效分钟数（≥1）')


async def media_autodelete_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检测媒体消息，命中则定时删除。"""
    msg = update.message
    if not msg:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    if not is_media_message(msg):
        return False

    s = await database.get_media_autodelete_settings(chat.id)
    if not s["enabled"]:
        return False

    delay = max(1, s.get("delete_minutes", 5)) * 60
    asyncio.create_task(_del_media(context.bot, chat.id, msg.message_id, delay))
    return True


async def _del_media(bot, chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
