import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database
from database import validate_column_name

logger = logging.getLogger(__name__)
logger.info("autodelete module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
BACK_EMOJI_ID = "5875082500023258804"
SWEEP_EMOJI_ID = "5927054181285237634"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

KEYS = {"pin": "置顶", "photo": "修改头像", "title": "修改名称"}


async def get_autodelete_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, pin, photo, title FROM group_autodelete WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"chat_id": row[0], "pin": bool(row[1]), "photo": bool(row[2]), "title": bool(row[3])}
    except Exception as e:
        logger.error(f"get_autodelete_settings err: {e}", exc_info=True)
    return {"chat_id": chat_id, "pin": False, "photo": False, "title": False}


async def update_autodelete_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_autodelete (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_autodelete SET {', '.join(parts)} WHERE chat_id = %s", vals)
    except Exception as e:
        logger.error(f"update_autodelete_settings err: {e}", exc_info=True)


def get_autodelete_keyboard(chat_id: str, settings: dict) -> InlineKeyboardMarkup:
    keyboard = []
    for k, v in KEYS.items():
        status = settings[k]
        keyboard.append([InlineKeyboardButton(
            f'{v}: {"开启" if status else "关闭"}',
            callback_data=f"ad_toggle_{chat_id}_{k}",
            icon_custom_emoji_id=CHECK_EMOJI_ID if status else CROSS_EMOJI_ID
        )])
    keyboard.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_autodelete_channel_keyboard(chat_id: str, settings: dict) -> InlineKeyboardMarkup:
    keyboard = []
    for k, v in KEYS.items():
        status = settings[k]
        keyboard.append([InlineKeyboardButton(
            f'{v}: {"开启" if status else "关闭"}',
            callback_data=f"ad_toggle_{chat_id}_{k}",
            icon_custom_emoji_id=CHECK_EMOJI_ID if status else CROSS_EMOJI_ID
        )])
    keyboard.append([InlineKeyboardButton("« 返回频道管理", callback_data=f"manage_channel_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


async def autodelete_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    chat_id = int(data.split("_")[2])

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("ad_panel_"):
        await query.answer()
        settings = await get_autodelete_settings(chat_id)
        try:
            chat = await context.bot.get_chat(chat_id)
            is_channel = chat.type == "channel"
        except Exception:
            is_channel = False
        check_icon = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>'
        cross_icon = f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
        text = f'<tg-emoji emoji-id="{SWEEP_EMOJI_ID}">🧹</tg-emoji> <b>自动删除</b>\n\n帮助您自动清理{"频道" if is_channel else "群组"}中的系统消息\n'
        for k, v in KEYS.items():
            text += f'\n{v}: {check_icon + " 开启" if settings[k] else cross_icon + " 关闭"}'
        kb = get_autodelete_channel_keyboard(str(chat_id), settings) if is_channel else get_autodelete_keyboard(str(chat_id), settings)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("ad_toggle_"):
        key = data.split("_")[-1]
        settings = await get_autodelete_settings(chat_id)
        new_val = not settings[key]
        await update_autodelete_settings(chat_id, **{key: new_val})
        await query.answer(f'{KEYS[key]}: {"开启" if new_val else "关闭"}')
        await query.message.delete()
        settings = await get_autodelete_settings(chat_id)
        try:
            chat = await context.bot.get_chat(chat_id)
            is_channel = chat.type == "channel"
        except Exception:
            is_channel = False
        check_icon = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>'
        cross_icon = f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
        text = f'<tg-emoji emoji-id="{SWEEP_EMOJI_ID}">🧹</tg-emoji> <b>自动删除</b>\n\n帮助您自动清理{"频道" if is_channel else "群组"}中的系统消息\n'
        for k, v in KEYS.items():
            text += f'\n{v}: {check_icon + " 开启" if settings[k] else cross_icon + " 关闭"}'
        kb = get_autodelete_channel_keyboard(str(chat_id), settings) if is_channel else get_autodelete_keyboard(str(chat_id), settings)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=kb)
        return


async def autodelete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.channel_post
    if not msg:
        return
    chat_id = msg.chat_id
    settings = await get_autodelete_settings(chat_id)

    if settings["pin"] and msg.pinned_message:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
            logger.info(f"autodelete: deleted pin message in {chat_id}")
        except Exception:
            pass

    if settings["photo"] and msg.new_chat_photo:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
            logger.info(f"autodelete: deleted photo change in {chat_id}")
        except Exception:
            pass

    if settings["title"] and msg.new_chat_title:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
            logger.info(f"autodelete: deleted title change in {chat_id}")
        except Exception:
            pass
