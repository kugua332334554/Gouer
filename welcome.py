import logging
import asyncio
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_welcome_settings, update_welcome_settings

logger = logging.getLogger(__name__)

DEFAULT_EMOJI_ID = "4963072209334567688"
CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
FROG_EMOJI_ID = "5355051922862653659"
CAMERA_EMOJI_ID = "5771695636411847302"
LINK_EMOJI_ID = "5879585266426973039"
TEXT_EMOJI_ID = "5879895758202735862"
WARN_EMOJI_ID = "5447644880824181073"
STAR_EMOJI_ID = "6323440286445867472"


def get_message_html(message) -> str:
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities
    if not text:
        return ""
    if not entities:
        return html.escape(text)
    utf16_bytes = text.encode("utf-16-le")
    events = []
    for entity in entities:
        start = entity.offset * 2
        end = (entity.offset + entity.length) * 2
        open_tag = None
        close_tag = None
        etype = getattr(entity, "type", "")
        etype_str = str(etype)
        if "custom_emoji" in etype_str or etype == "custom_emoji":
            emoji_id = getattr(entity, "custom_emoji_id", None)
            if emoji_id:
                open_tag = f'<tg-emoji emoji-id="{emoji_id}">'
                close_tag = "</tg-emoji>"
        elif "bold" in etype_str or etype == "bold":
            open_tag = "<b>"
            close_tag = "</b>"
        elif "italic" in etype_str or etype == "italic":
            open_tag = "<i>"
            close_tag = "</i>"
        elif "code" in etype_str or etype == "code":
            open_tag = "<code>"
            close_tag = "</code>"
        elif "pre" in etype_str or etype == "pre":
            open_tag = "<pre>"
            close_tag = "</pre>"
        elif "underline" in etype_str or etype == "underline":
            open_tag = "<u>"
            close_tag = "</u>"
        elif "strikethrough" in etype_str or etype == "strikethrough":
            open_tag = "<s>"
            close_tag = "</s>"
        elif "spoiler" in etype_str or etype == "spoiler":
            open_tag = "<tg-spoiler>"
            close_tag = "</tg-spoiler>"
        elif "text_link" in etype_str or etype == "text_link":
            url = getattr(entity, "url", "")
            open_tag = f'<a href="{html.escape(url)}">'
            close_tag = "</a>"
        elif "blockquote" in etype_str or etype == "blockquote":
            open_tag = "<blockquote>"
            close_tag = "</blockquote>"
        if open_tag and close_tag:
            events.append((start, 1, open_tag))
            events.append((end, 0, close_tag))
    events.sort(key=lambda x: (x[0], x[1]))
    result = []
    last_idx = 0
    for offset, _, tag in events:
        if offset > last_idx:
            chunk = utf16_bytes[last_idx:offset].decode("utf-16-le")
            result.append(html.escape(chunk))
        result.append(tag)
        last_idx = offset
    if last_idx < len(utf16_bytes):
        chunk = utf16_bytes[last_idx:].decode("utf-16-le")
        result.append(html.escape(chunk))
    return "".join(result)


def preprocess_button_text(message) -> str:
    text = message.text or ""
    entities = message.entities or []
    if not text or not entities:
        return text
    utf16_bytes = text.encode("utf-16-le")
    custom_emoji_entities = []
    for e in entities:
        etype_str = str(getattr(e, "type", ""))
        emoji_id = getattr(e, "custom_emoji_id", None)
        if ("custom_emoji" in etype_str or e.type == "custom_emoji") and emoji_id:
            custom_emoji_entities.append((e.offset, e.length, str(emoji_id)))
    if not custom_emoji_entities:
        return text
    custom_emoji_entities.sort(key=lambda x: x[0], reverse=True)
    for offset, length, emoji_id in custom_emoji_entities:
        start = offset * 2
        end = (offset + length) * 2
        before = utf16_bytes[:start].decode("utf-16-le")
        after = utf16_bytes[end:].decode("utf-16-le")
        text = before + emoji_id + after
    return text


def parse_welcome_buttons(buttons_text: str):
    if not buttons_text:
        return None
    color_map = {
        "红色": "danger",
        "绿色": "success",
        "蓝色": "primary"
    }
    keyboard = []
    lines = buttons_text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        row = []
        btn_configs = line.split("&&")
        for btn_cfg in btn_configs:
            btn_cfg = btn_cfg.strip()
            if not btn_cfg:
                continue
            parts = [p.strip() for p in btn_cfg.split("-")]
            if len(parts) < 2:
                continue
            style = None
            icon_custom_emoji_id = None
            if parts[0] in color_map:
                style = color_map[parts.pop(0)]
            if parts and parts[0].isdigit() and len(parts[0]) >= 5:
                icon_custom_emoji_id = parts.pop(0)
            if len(parts) >= 2:
                url = parts[-1]
                text = "-".join(parts[:-1])
                kwargs = {"text": text, "url": url}
                if style:
                    kwargs["style"] = style
                if icon_custom_emoji_id:
                    kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
                row.append(InlineKeyboardButton(**kwargs))
        if row:
            keyboard.append(row)
    return InlineKeyboardMarkup(keyboard) if keyboard else None


def get_welcome_text(state: dict) -> str:
    status_text = (
        f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> 开启'
        if state['status']
        else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji> 关闭'
    )
    delete_info = []
    if state['delete_last']:
        delete_info.append("删除上一条")
    if state['delete_time'] > 0:
        delete_info.append(f"{state['delete_time']}分钟")
    if not delete_info:
        delete_str = "否"
    else:
        delete_str = " / ".join(delete_info)
    has_media = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if state.get('media_file_id') else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    has_buttons = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if state.get('buttons_text') else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    has_text = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if state.get('welcome_text') else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    return (
        f'<tg-emoji emoji-id="{FROG_EMOJI_ID}">🐸</tg-emoji> <b>进群欢迎</b>\n\n'
        f'<b>状态:</b> {status_text}\n\n'
        f'<b>删除消息:</b> {delete_str}\n\n'
        f'<b>自定义欢迎内容:</b>\n'
        f'├ <tg-emoji emoji-id="{CAMERA_EMOJI_ID}">📷</tg-emoji> 媒体图片: {has_media}\n'
        f'├ <tg-emoji emoji-id="{LINK_EMOJI_ID}">🔗</tg-emoji> 链接按钮: {has_buttons}\n'
        f'└ <tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> 文本内容: {has_text}'
    )


def get_welcome_keyboard(chat_id: str, state: dict) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton("状态:", callback_data="noop"),
        InlineKeyboardButton(
            "开启",
            callback_data=f"wel_set_status_1_{chat_id}",
            style="primary" if state['status'] else "default",
            icon_custom_emoji_id=CHECK_EMOJI_ID if state['status'] else None
        ),
        InlineKeyboardButton(
            "关闭",
            callback_data=f"wel_set_status_0_{chat_id}",
            style="primary" if not state['status'] else "default",
            icon_custom_emoji_id=CROSS_EMOJI_ID if not state['status'] else None
        )
    ]
    row2 = [InlineKeyboardButton("删除消息(分钟)", callback_data="noop")]
    def dt_kwargs(val):
        if state['delete_time'] == val:
            return {"style": "primary", "icon_custom_emoji_id": CHECK_EMOJI_ID}
        return {"style": "default"}
    row3 = [
        InlineKeyboardButton("否", callback_data=f"wel_set_dt_0_{chat_id}", **dt_kwargs(0)),
        InlineKeyboardButton("1", callback_data=f"wel_set_dt_1_{chat_id}", **dt_kwargs(1)),
        InlineKeyboardButton("5", callback_data=f"wel_set_dt_5_{chat_id}", **dt_kwargs(5)),
        InlineKeyboardButton("10", callback_data=f"wel_set_dt_10_{chat_id}", **dt_kwargs(10))
    ]
    row4 = [
        InlineKeyboardButton(
            "删除上一条",
            callback_data=f"wel_set_dellast_{chat_id}",
            style="primary" if state['delete_last'] else "default",
            icon_custom_emoji_id=CHECK_EMOJI_ID if state['delete_last'] else None
        )
    ]
    row5 = [InlineKeyboardButton("预览消息", callback_data=f"wel_preview_{chat_id}", icon_custom_emoji_id="5960714428394507968")]
    row6 = [
        InlineKeyboardButton("修改文本", callback_data=f"wel_edit_text_{chat_id}", icon_custom_emoji_id="5884510167986343350"),
        InlineKeyboardButton("修改媒体", callback_data=f"wel_edit_media_{chat_id}", icon_custom_emoji_id="5395440575543520059")
    ]
    row7 = [InlineKeyboardButton("修改按钮", callback_data=f"wel_edit_btn_{chat_id}", icon_custom_emoji_id="5879841310902324730")]
    row8 = [InlineKeyboardButton("« 返回", callback_data=f"manage_group_{chat_id}")]
    return InlineKeyboardMarkup([row1, row2, row3, row4, row5, row6, row7, row8])


async def send_welcome_panel(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_chat_id: int):
    state = await get_welcome_settings(chat_id)
    text = get_welcome_text(state)
    reply_markup = get_welcome_keyboard(str(chat_id), state)
    await context.bot.send_message(
        chat_id=target_chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def welcome_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    action = parts[1]
    sub_action = parts[2] if len(parts) > 2 else ""
    chat_id = parts[-1]
    state = await get_welcome_settings(int(chat_id))

    if action == "cancel":
        context.user_data.pop("await_welcome_input", None)
        await query.answer("已取消编辑")
        await send_welcome_panel(context, int(chat_id), update.effective_chat.id)
        return

    if action == "set":
        if sub_action == "status":
            val = int(parts[3])
            state["status"] = bool(val)
        elif sub_action == "dt":
            val = int(parts[3])
            state["delete_time"] = val
        elif sub_action == "dellast":
            state["delete_last"] = not state["delete_last"]
        await update_welcome_settings(int(chat_id), **state)
        await query.answer("设置已更新！")
        await query.edit_message_text(
            text=get_welcome_text(state),
            parse_mode="HTML",
            reply_markup=get_welcome_keyboard(chat_id, state)
        )

    elif action == "preview":
        await query.answer("正在发送预览...")
        try:
            group_chat = await context.bot.get_chat(int(chat_id))
            await send_welcome_message(
                context,
                group_chat,
                update.effective_user,
                is_preview=True,
                target_chat_id=update.effective_chat.id
            )
        except Exception as e:
            logger.error(f"preview fail: {e}", exc_info=True)
            await query.message.reply_html(
                f'<tg-emoji emoji-id="{WARN_EMOJI_ID}">⚠️</tg-emoji> 预览发送失败，请确认机器人仍在目标群组中。'
            )

    elif action == "edit":
        context.user_data["await_welcome_input"] = {"type": sub_action, "chat_id": chat_id}
        cancel_btn = InlineKeyboardButton("« 取消", callback_data=f"wel_cancel_{chat_id}")
        reply_markup = InlineKeyboardMarkup([[cancel_btn]])

        if sub_action == "text":
            current_text = state.get("welcome_text", "欢迎 {MENTION} 加入本群")
            prompt = (
                "编辑欢迎语：现在输入文本设置你的欢迎内容\n\n"
                "支持 HTML 和文字字体格式（加粗、链接、删透、块引用、<b>自定义会员表情</b>等）\n"
                "及以下变量:\n"
                "• {NAME} - 用户名\n"
                "• {MENTION} - 用户名和链接\n"
                "• {GROUPNAME} - 群组名\n\n"
                f"当前内容：\n<blockquote>{current_text}</blockquote>"
            )
            await query.message.reply_html(prompt, reply_markup=reply_markup)

        elif sub_action == "media":
            prompt = "欢迎媒体支持：请发送图片或视频，文件大小不超过 5MB"
            await query.message.reply_html(prompt, reply_markup=reply_markup)

        elif sub_action == "btn":
            prompt = (
                "请发送按钮配置，格式：颜色（可选）-会员图标/表情（可选）-按钮文字-链接地址\n\n"
                "提示：您可以直接在消息中插入/选择 Telegram 会员表情，系统将自动识别！\n\n"
                "用 && 分隔同行多个按钮，换行分行\n\n"
                "示例：\n"
                "官方频道-https://t.me/channel\n"
                "红色-按钮1-https://a.com && 按钮2-https://b.com"
            )
            await query.message.reply_html(prompt, reply_markup=reply_markup)


async def welcome_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await_data = context.user_data.get("await_welcome_input")
    if not await_data:
        return
    chat_id = int(await_data["chat_id"])
    input_type = await_data["type"]
    message = update.message

    if input_type == "text":
        new_text = get_message_html(message)
        await update_welcome_settings(chat_id, welcome_text=new_text)
        await message.reply_html(
            f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> 欢迎文本已更新！'
        )
        await send_welcome_panel(context, chat_id, update.effective_chat.id)

    elif input_type == "media":
        media_type = None
        media_file_id = None
        file_size = 0
        if message.photo:
            photo = message.photo[-1]
            file_size = photo.file_size or 0
            media_type = "photo"
            media_file_id = photo.file_id
        elif message.video:
            video = message.video
            file_size = video.file_size or 0
            media_type = "video"
            media_file_id = video.file_id
        else:
            await message.reply_html(
                f'<tg-emoji emoji-id="{WARN_EMOJI_ID}">⚠️</tg-emoji> 未识别到有效的图片或视频，请重新发送！'
            )
            return
        if file_size > 5 * 1024 * 1024:
            await message.reply_html(
                f'<tg-emoji emoji-id="{WARN_EMOJI_ID}">⚠️</tg-emoji> 媒体文件大小超过 5MB 限制，请处理后重新发送！'
            )
            return
        await update_welcome_settings(chat_id, media_type=media_type, media_file_id=media_file_id)
        await message.reply_html(
            f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> 欢迎媒体已更新！'
        )
        await send_welcome_panel(context, chat_id, update.effective_chat.id)

    elif input_type == "buttons":
        raw_text = message.text or ""
        if raw_text.strip() in ["清空", "清除", "clear"]:
            await update_welcome_settings(chat_id, buttons_text="")
            await message.reply_html(
                f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> 按钮已清空！'
            )
            await send_welcome_panel(context, chat_id, update.effective_chat.id)
            context.user_data.pop("await_welcome_input", None)
            return
        processed_text = preprocess_button_text(message)
        markup = parse_welcome_buttons(processed_text)
        if not markup:
            await message.reply_html(
                f'<tg-emoji emoji-id="{WARN_EMOJI_ID}">⚠️</tg-emoji> 按钮格式错误，请参照示例重新输入！'
            )
            return
        await update_welcome_settings(chat_id, buttons_text=processed_text)
        await message.reply_html(
            f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> 欢迎按钮已更新！'
        )
        await send_welcome_panel(context, chat_id, update.effective_chat.id)

    context.user_data.pop("await_welcome_input", None)


async def send_welcome_message(context: ContextTypes.DEFAULT_TYPE, chat, user, is_preview=False, target_chat_id=None):
    state = await get_welcome_settings(chat.id)
    if not state["status"] and not is_preview:
        return
    name = user.full_name or user.first_name
    mention = f'<a href="tg://user?id={user.id}">{name}</a>'
    group_name = chat.title or "本群"
    welcome_text = state.get("welcome_text") or "欢迎 {MENTION} 加入本群"
    rendered_text = (
        welcome_text
        .replace("{NAME}", name)
        .replace("{MENTION}", mention)
        .replace("{GROUPNAME}", group_name)
    )
    reply_markup = parse_welcome_buttons(state.get("buttons_text"))
    send_chat_id = target_chat_id if target_chat_id is not None else chat.id
    if state.get("delete_last") and state.get("last_msg_id") and not is_preview and target_chat_id is None:
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=state["last_msg_id"])
        except Exception:
            pass
    sent_msg = None
    media_type = state.get("media_type")
    media_file_id = state.get("media_file_id")
    try:
        if media_type == "photo" and media_file_id:
            sent_msg = await context.bot.send_photo(
                chat_id=send_chat_id,
                photo=media_file_id,
                caption=rendered_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        elif media_type == "video" and media_file_id:
            sent_msg = await context.bot.send_video(
                chat_id=send_chat_id,
                video=media_file_id,
                caption=rendered_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            sent_msg = await context.bot.send_message(
                chat_id=send_chat_id,
                text=rendered_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        if sent_msg and not is_preview and target_chat_id is None:
            await update_welcome_settings(chat.id, last_msg_id=sent_msg.message_id)
            delete_time = state.get("delete_time", 0)
            if delete_time > 0:
                asyncio.create_task(delete_delay_message(context.bot, chat.id, sent_msg.message_id, delete_time * 60))
    except Exception as e:
        logger.error(f"send welcome msg fail: {e}", exc_info=True)


async def delete_delay_message(bot, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass
