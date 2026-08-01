import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
import database
from database import validate_column_name

logger = logging.getLogger(__name__)
logger.info("toggle_group module loaded")

CHECK_EMOJI = "5776375003280838798"
CROSS_EMOJI = "5778527486270770928"
SETTINGS_EMOJI = "5931409969613116639"
ADD_EMOJI = "5775937998948404844"
TEXT_EMOJI = "5879895758202735862"
MEDIA_EMOJI = "5879841310902324730"
BTN_EMOJI = "5985774024968379294"
LOCK_EMOJI = "5363972600001216334"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'

_AWAIT_TOGGLE = {}  # user_id → {chat_id, field}


def get_toggle_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    on_off = "✅" if s["enabled"] else "❌"
    okw = s["open_keyword"] or "未设置"
    ckw = s["close_keyword"] or "未设置"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"功能: {on_off}", callback_data=f"tg_toggle_{chat_id}", icon_custom_emoji_id=CHECK_EMOJI if s["enabled"] else CROSS_EMOJI)],
        [InlineKeyboardButton(f"开群关键词: {okw}", callback_data=f"tg_setopenkw_{chat_id}", icon_custom_emoji_id=TEXT_EMOJI)],
        [InlineKeyboardButton("开群提示", callback_data=f"tg_setopentext_{chat_id}", icon_custom_emoji_id=TEXT_EMOJI)],
        [InlineKeyboardButton("开群媒体", callback_data=f"tg_setopenmedia_{chat_id}", icon_custom_emoji_id=MEDIA_EMOJI)],
        [InlineKeyboardButton("开群按钮", callback_data=f"tg_setopenbtn_{chat_id}", icon_custom_emoji_id=BTN_EMOJI)],
        [InlineKeyboardButton(f"关群关键词: {ckw}", callback_data=f"tg_setclosekw_{chat_id}", icon_custom_emoji_id=TEXT_EMOJI)],
        [InlineKeyboardButton("关群提示", callback_data=f"tg_setclosetext_{chat_id}", icon_custom_emoji_id=TEXT_EMOJI)],
        [InlineKeyboardButton("关群媒体", callback_data=f"tg_setclosemedia_{chat_id}", icon_custom_emoji_id=MEDIA_EMOJI)],
        [InlineKeyboardButton("关群按钮", callback_data=f"tg_setclosebtn_{chat_id}", icon_custom_emoji_id=BTN_EMOJI)],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]
    ])


async def toggle_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    try:
        # chat_id is always the last _ part
        parts = data.split("_")
        chat_id = int(parts[-1])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception:
        return

    # ── 主面板 ──
    if data.startswith("tg_panel_"):
        await query.answer()
        s = await database.get_toggle_settings(chat_id)
        ok = s["open_keyword"] or "未设置"
        ck = s["close_keyword"] or "未设置"
        text = f'<tg-emoji emoji-id="{LOCK_EMOJI}">🔒</tg-emoji> <b>开关群</b>\n\n状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}\n当前: {"🔓 已开放" if s.get("_is_open", True) else "🔒 已关闭"}\n\n开群关键词: {ok}\n关群关键词: {ck}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_toggle_keyboard(str(chat_id), s))
        return

    # ── 功能开关 ──
    if data.startswith("tg_toggle_"):
        s = await database.get_toggle_settings(chat_id)
        await database.update_toggle_settings(chat_id, enabled=not s["enabled"])
        await query.answer(f'已{"开启" if not s["enabled"] else "关闭"}')
        s = await database.get_toggle_settings(chat_id)
        ok = s["open_keyword"] or "未设置"
        ck = s["close_keyword"] or "未设置"
        text = f'<tg-emoji emoji-id="{LOCK_EMOJI}">🔒</tg-emoji> <b>开关群</b>\n\n状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}\n\n开群关键词: {ok}\n关群关键词: {ck}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_toggle_keyboard(str(chat_id), s))
        return

    # ── 设置文本/关键词/按钮 → 等待输入 ──
    field_map = {
        "tg_setopenkw_": ("open_keyword", "开群关键词"),
        "tg_setclosekw_": ("close_keyword", "关群关键词"),
    }
    for prefix, (field, label) in field_map.items():
        if data.startswith(prefix):
            await query.answer()
            chat_id = int(data.split("_")[-1])
            _AWAIT_TOGGLE[user_id] = {"chat_id": chat_id, "field": field, "conv_chat": update.effective_chat.id}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"tg_panel_{chat_id}")]])
            await query.message.reply_html(f"请发送<b>{label}</b>:", reply_markup=kb)
            return

    # ── 提示文本多行 ──
    text_fields = {
        "tg_setopentext_": ("open_text", "开群提示"),
        "tg_setclosetext_": ("close_text", "关群提示"),
    }
    for prefix, (field, label) in text_fields.items():
        if data.startswith(prefix):
            await query.answer()
            chat_id = int(data.split("_")[-1])
            _AWAIT_TOGGLE[user_id] = {"chat_id": chat_id, "field": field, "conv_chat": update.effective_chat.id}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"tg_panel_{chat_id}")]])
            await query.message.reply_html(
                f"请发送<b>{label}</b>文字\n支持高级版表情和 HTML\n发送 <code>0</code> 清除",
                reply_markup=kb)
            return

    # ── 媒体（图片/视频/GIF）──
    media_fields = {
        "tg_setopenmedia_": ("open_media", "开群媒体"),
        "tg_setclosemedia_": ("close_media", "关群媒体"),
    }
    for prefix, (field, label) in media_fields.items():
        if data.startswith(prefix):
            await query.answer()
            chat_id = int(data.split("_")[-1])
            _AWAIT_TOGGLE[user_id] = {"chat_id": chat_id, "field": field, "conv_chat": update.effective_chat.id}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"tg_panel_{chat_id}")]])
            await query.message.reply_html(
                f"请发送<b>{label}</b>（图片/视频/GIF）\n发送 <code>0</code> 清除",
                reply_markup=kb)
            return

    # ── 按钮 ──
    btn_fields = {
        "tg_setopenbtn_": ("open_buttons_text", "开群按钮"),
        "tg_setclosebtn_": ("close_buttons_text", "关群按钮"),
    }
    for prefix, (field, label) in btn_fields.items():
        if data.startswith(prefix):
            await query.answer()
            chat_id = int(data.split("_")[-1])
            _AWAIT_TOGGLE[user_id] = {"chat_id": chat_id, "field": field, "conv_chat": update.effective_chat.id}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"tg_panel_{chat_id}")]])
            await query.message.reply_html(
                f"请发送<b>{label}</b>配置：\n\n"
                f"格式：<b>颜色（可选）-按钮文字-链接</b>\n"
                f"颜色可选：红色 / 绿色 / 蓝色（也可以只写 红 / 绿 / 蓝）\n"
                f"<b>按钮图标</b>：直接在消息里插入 Telegram 会员表情即可自动识别\n"
                f"用 <b>&&</b> 分隔同行，<b>换行</b>分行\n\n"
                f"示例：\n<code>蓝色-官方频道-https://t.me/channel</code>\n"
                f"<code>红色-按钮1-https://a.com && 绿色-按钮2-https://b.com</code>\n\n"
                f"发送 <code>0</code> 清除",
                reply_markup=kb)
            return


# ── 输入处理 ──────────────────────────────────────

async def toggle_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in _AWAIT_TOGGLE:
        return
    # 只消费在发起设置的同一会话里的消息，避免把其他会话的普通发言当成设置输入
    if update.effective_chat is None or update.effective_chat.id != _AWAIT_TOGGLE.get(user_id, {}).get("conv_chat"):
        return
    msg = update.message
    if not msg:
        return
    info = _AWAIT_TOGGLE.pop(user_id)
    chat_id = info["chat_id"]
    field = info["field"]

    # 媒体处理
    if field in ("open_media", "close_media"):
        if msg.text and msg.text.strip() == "0":
            mtype = field.replace("_media", "")
            await database.update_toggle_settings(chat_id, **{f"{mtype}_media_type": "", f"{mtype}_media_file_id": ""})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已清除")
        elif msg.photo:
            fid = msg.photo[-1].file_id
            mtype = field.replace("_media", "")
            await database.update_toggle_settings(chat_id, **{f"{mtype}_media_type": "photo", f"{mtype}_media_file_id": fid})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已保存图片")
        elif msg.video:
            mtype = field.replace("_media", "")
            await database.update_toggle_settings(chat_id, **{f"{mtype}_media_type": "video", f"{mtype}_media_file_id": msg.video.file_id})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已保存视频")
        elif msg.animation:
            mtype = field.replace("_media", "")
            await database.update_toggle_settings(chat_id, **{f"{mtype}_media_type": "animation", f"{mtype}_media_file_id": msg.animation.file_id})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已保存 GIF")
        else:
            await msg.reply_html(f"{EMOJI_WARN} 请发送图片/视频/GIF，或 0 清除")
        return

    # 文本处理
    raw = msg.text or msg.caption or ""
    raw = raw.strip()

    if field in ("open_text", "close_text", "open_keyword", "close_keyword"):
        if raw == "0":
            await database.update_toggle_settings(chat_id, **{field: ""})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已清除")
        else:
            await database.update_toggle_settings(chat_id, **{field: raw})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已保存")
        s = await database.get_toggle_settings(chat_id)
        text = f'<tg-emoji emoji-id="{LOCK_EMOJI}">🔒</tg-emoji> <b>开关群</b>\n\n状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML",
            reply_markup=get_toggle_keyboard(str(chat_id), s))
        return

    # 按钮处理
    if field in ("open_buttons_text", "close_buttons_text"):
        from welcome import parse_welcome_buttons, preprocess_button_text
        if raw == "0":
            await database.update_toggle_settings(chat_id, **{field: ""})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已清除")
        else:
            processed = preprocess_button_text(msg)
            markup = parse_welcome_buttons(processed)
            if not markup:
                await msg.reply_html(f"{EMOJI_WARN} 按钮格式错误，请参照示例重新输入！")
                return
            await database.update_toggle_settings(chat_id, **{field: processed})
            await msg.reply_html(f"{EMOJI_SUCCESS} 已保存")
        s = await database.get_toggle_settings(chat_id)
        text = f'<tg-emoji emoji-id="{LOCK_EMOJI}">🔒</tg-emoji> <b>开关群</b>\n\n状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML",
            reply_markup=get_toggle_keyboard(str(chat_id), s))
        return


# ── 关键词检测 ────────────────────────────────────

async def check_toggle_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检测开关群关键词，返回 True 已拦截"""
    msg = update.message
    if not msg or not msg.text:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    user = update.effective_user
    if not user or user.is_bot:
        return False

    s = await database.get_toggle_settings(chat.id)
    if not s["enabled"]:
        return False

    text = msg.text.strip()
    open_kw = s["open_keyword"].strip()
    close_kw = s["close_keyword"].strip()

    is_open_cmd = open_kw and text == open_kw
    is_close_cmd = close_kw and text == close_kw

    if not is_open_cmd and not is_close_cmd:
        return False

    # 检查管理员权限
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            return False
    except Exception:
        return False

    prefix = "open" if is_open_cmd else "close"
    txt = s[f"{prefix}_text"] or ""
    mtype = s[f"{prefix}_media_type"] or ""
    mfile = s[f"{prefix}_media_file_id"] or ""
    btns_raw = s[f"{prefix}_buttons_text"] or ""

    # 构建按钮
    from welcome import parse_welcome_buttons
    reply_markup = parse_welcome_buttons(btns_raw) if btns_raw else None

    # 发媒体
    try:
        if mtype == "photo" and mfile:
            await context.bot.send_photo(chat.id, photo=mfile, caption=txt or None,
                                         parse_mode="HTML" if txt else None, reply_markup=reply_markup)
        elif mtype == "video" and mfile:
            await context.bot.send_video(chat.id, video=mfile, caption=txt or None,
                                         parse_mode="HTML" if txt else None, reply_markup=reply_markup)
        elif mtype == "animation" and mfile:
            await context.bot.send_animation(chat.id, animation=mfile, caption=txt or None,
                                             parse_mode="HTML" if txt else None, reply_markup=reply_markup)
        elif txt:
            await context.bot.send_message(chat.id, text=txt, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"toggle send media failed: {e}")

    # 执行开/关群
    try:
        if is_open_cmd:
            await context.bot.set_chat_permissions(chat.id, ChatPermissions(
                can_send_messages=True, can_send_audios=True,
                can_send_documents=True, can_send_photos=True,
                can_send_videos=True, can_send_video_notes=True,
                can_send_voice_notes=True, can_send_polls=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
                can_change_info=False, can_invite_users=True, can_pin_messages=False
            ))
        else:
            await context.bot.set_chat_permissions(chat.id, ChatPermissions(
                can_send_messages=False, can_send_audios=False,
                can_send_documents=False, can_send_photos=False,
                can_send_videos=False, can_send_video_notes=False,
                can_send_voice_notes=False, can_send_polls=False,
                can_send_other_messages=False, can_add_web_page_previews=False,
                can_change_info=False, can_invite_users=False, can_pin_messages=False
            ))
    except Exception as e:
        logger.error(f"toggle set_chat_permissions failed: {e}")

    return True
