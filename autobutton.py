import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database
from lang import t

logger = logging.getLogger(__name__)
logger.info("autobutton module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
BTN_EMOJI_ID = "5879841310902324730"
BACK_EMOJI_ID = "5875082500023258804"
DELETE_EMOJI_ID = "6017288111279575194"
ADD_EMOJI_ID = "5775937998948404844"
TEXT_EMOJI_ID = "5879895758202735862"
MEDIA_EMOJI_ID = "5395440575543520059"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'

_AWAIT_AUTOBUTTON = {}

from welcome import preprocess_button_text, parse_welcome_buttons


async def get_autobutton_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, status, buttons_text FROM channel_autobutton WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"chat_id": row[0], "status": bool(row[1]), "buttons_text": row[2] or ""}
    except Exception as e:
        logger.error(f"get_autobutton_settings err: {e}", exc_info=True)
    return {"chat_id": chat_id, "status": False, "buttons_text": ""}


async def update_autobutton_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO channel_autobutton (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{k}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE channel_autobutton SET {', '.join(parts)} WHERE chat_id = %s", vals)
    except Exception as e:
        logger.error(f"update_autobutton_settings err: {e}", exc_info=True)


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return
    chat_id = msg.chat_id
    logger.info(f"channel_post_handler FIRED: chat={chat_id}, msg_id={msg.message_id}, has_text={bool(msg.text)}, has_photo={bool(msg.photo)}")
    settings = await get_autobutton_settings(chat_id)
    if not settings["status"]:
        logger.info(f"channel_post_handler: autobutton disabled for chat {chat_id}")
        return
    if not settings["buttons_text"]:
        logger.info(f"channel_post_handler: no buttons configured for chat {chat_id}")
        return
    try:
        markup = parse_welcome_buttons(settings["buttons_text"])
        if markup:
            await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg.message_id, reply_markup=markup)
            logger.info(f"channel_post_handler: SUCCESS edited msg {msg.message_id}")
    except Exception as e:
        logger.error(f"channel_post_handler edit err: {e}")


def get_autobutton_keyboard(chat_id: str, settings: dict) -> InlineKeyboardMarkup:
    status_text = "开启" if settings["status"] else "关闭"
    status_icon = CHECK_EMOJI_ID if settings["status"] else CROSS_EMOJI_ID
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f'自动按钮: {status_text}', callback_data=f"ab_toggle_{chat_id}", icon_custom_emoji_id=status_icon)],
        [InlineKeyboardButton("编辑按钮", callback_data=f"ab_editbtn_{chat_id}", icon_custom_emoji_id=BTN_EMOJI_ID)],
        [InlineKeyboardButton("« 返回频道管理", callback_data=f"manage_channel_{chat_id}")]
    ])


async def autobutton_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    chat_id = int(data.split("_")[-1])

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("ab_panel_"):
        await query.answer()
        settings = await get_autobutton_settings(chat_id)
        title = await t(user_id, "autobtn_title") if user_id else "自动按钮"
        desc = await t(user_id, "autobtn_desc") if user_id else "检测到频道新消息后自动编辑添加按钮"
        st = await t(user_id, "status") if user_id else "状态"
        enable_text = await t(user_id, "enable") if user_id else "开启"
        disable_text = await t(user_id, "disable") if user_id else "关闭"
        status_text = enable_text if settings["status"] else disable_text
        empty_text = await t(user_id, "autobtn_empty") if user_id else "未设置"
        btn_preview = settings["buttons_text"][:100] if settings["buttons_text"] else empty_text
        text = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>{title}</b>\n\n{desc}\n\n{st}：{status_text}\n{await t(user_id, "autobtn_edit") if user_id else "编辑按钮"}：{btn_preview}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_autobutton_keyboard(str(chat_id), settings))
        return

    if data.startswith("ab_toggle_"):
        settings = await get_autobutton_settings(chat_id)
        await update_autobutton_settings(chat_id, status=not settings["status"])
        settings = await get_autobutton_settings(chat_id)
        enabled_text = await t(user_id, "autobtn_enabled") if user_id else "已开启"
        disabled_text = await t(user_id, "autobtn_disabled") if user_id else "已关闭"
        await query.answer(enabled_text if settings["status"] else disabled_text)
        await query.message.delete()
        title = await t(user_id, "autobtn_title") if user_id else "自动按钮"
        desc = await t(user_id, "autobtn_desc") if user_id else "检测到频道新消息后自动编辑添加按钮"
        st = await t(user_id, "status") if user_id else "状态"
        enable_text = await t(user_id, "enable") if user_id else "开启"
        disable_text = await t(user_id, "disable") if user_id else "关闭"
        status_text = enable_text if settings["status"] else disable_text
        empty_text = await t(user_id, "autobtn_empty") if user_id else "未设置"
        btn_preview = settings["buttons_text"][:100] if settings["buttons_text"] else empty_text
        text = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>{title}</b>\n\n{desc}\n\n{st}：{status_text}\n{await t(user_id, "autobtn_edit") if user_id else "编辑按钮"}：{btn_preview}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_autobutton_keyboard(str(chat_id), settings))
        return

    if data.startswith("ab_editbtn_"):
        await query.answer()
        _AWAIT_AUTOBUTTON[user_id] = {"type": "edit_buttons", "chat_id": chat_id}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"ab_panel_{chat_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>编辑自动按钮</b>\n\n'
            f'格式：<b>颜色（可选）-会员表情ID-文字-链接</b>\n'
            f'颜色：红色(红) / 绿色(绿) / 蓝色(蓝)\n'
            f'用 <b>&&</b> 分隔同行，<b>换行</b>分行\n\n'
            f'示例：\n<code>蓝色-官方频道-https://t.me/channel</code>\n'
            f'<code>红色-按钮1-https://a.com && 绿色-按钮2-https://b.com</code>\n\n'
            f'发送 <code>清空</code> 清空按钮',
            reply_markup=kb
        )
        return


async def autobutton_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    await_data = _AWAIT_AUTOBUTTON.get(user_id)
    if not await_data:
        return
    message = update.message
    if message is None or not message.text:
        return
    raw = message.text.strip()
    chat_id = await_data["chat_id"]

    if raw in ["清空", "清除", "clear"]:
        await update_autobutton_settings(chat_id, buttons_text="")
        _AWAIT_AUTOBUTTON.pop(user_id, None)
        await message.reply_html(f"{EMOJI_SUCCESS} 按钮已清空！")
        settings = await get_autobutton_settings(chat_id)
        status_text = "开启" if settings["status"] else "关闭"
        text = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>自动按钮</b>\n\n状态：{status_text}\n当前按钮：未设置'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_autobutton_keyboard(str(chat_id), settings))
        return

    processed = preprocess_button_text(message)
    markup = parse_welcome_buttons(processed)
    if not markup:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"ab_panel_{chat_id}")]])
        await message.reply_html(f"{EMOJI_WARN} 格式错误！", reply_markup=kb)
        return
    await update_autobutton_settings(chat_id, buttons_text=processed)
    _AWAIT_AUTOBUTTON.pop(user_id, None)
    await message.reply_html(f"{EMOJI_SUCCESS} 自动按钮已设置！")
    settings = await get_autobutton_settings(chat_id)
    status_text = "开启" if settings["status"] else "关闭"
    text = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>自动按钮</b>\n\n状态：{status_text}\n当前按钮：{processed[:100]}'
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_autobutton_keyboard(str(chat_id), settings))
