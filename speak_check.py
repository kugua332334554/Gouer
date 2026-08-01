import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ChatMember
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
import database
from database import validate_column_name

logger = logging.getLogger(__name__)
logger.info("speak_check module loaded")

CHECK_EMOJI = "5776375003280838798"
CROSS_EMOJI = "5778527486270770928"
SETTINGS_EMOJI = "5931409969613116639"
BACK_EMOJI = "5875082500023258804"
SEARCH_EMOJI = "5994378914636500516"

WARN_EMOJI = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'

PENALTY_OPTIONS = {"mute": "禁言", "kick": "踢出", "ban": "封禁"}


def get_speak_check_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    def _on_off(v): return "✅开" if v else "❌关"
    def _icon(v): return CHECK_EMOJI if v else CROSS_EMOJI

    kb = [
        [InlineKeyboardButton(f"检查姓氏: {_on_off(s.get('require_last_name', False))}", callback_data=f"spk_lastname_{chat_id}", icon_custom_emoji_id=_icon(s.get("require_last_name", False)))],
        [InlineKeyboardButton(f"检查用户名: {_on_off(s.get('require_username', False))}", callback_data=f"spk_username_{chat_id}", icon_custom_emoji_id=_icon(s.get("require_username", False)))],
        [InlineKeyboardButton(f"检查头像: {_on_off(s.get('require_photo', False))}", callback_data=f"spk_photo_{chat_id}", icon_custom_emoji_id=_icon(s.get("require_photo", False)))],
        [InlineKeyboardButton(f"检查高级版: {_on_off(s.get('require_premium', False))}", callback_data=f"spk_premium_{chat_id}", icon_custom_emoji_id=_icon(s.get("require_premium", False)))],
        [InlineKeyboardButton(f"检查订阅频道: {_on_off(s.get('require_channel', False))}", callback_data=f"spk_channel_{chat_id}", icon_custom_emoji_id=_icon(s.get("require_channel", False)))],
    ]
    if s.get("require_channel"):
        ch = s.get("channel_username") or "点击设置"
        kb.append([InlineKeyboardButton(f"频道: @{ch}", callback_data=f"spk_setchannel_{chat_id}", icon_custom_emoji_id=SEARCH_EMOJI)])
    kb.append([
        InlineKeyboardButton(f"惩罚: {PENALTY_OPTIONS.get(s.get('penalty', 'mute'), '禁言')}", callback_data=f"spk_penalty_{chat_id}", icon_custom_emoji_id="5776213190387961618"),
    ])
    if s.get("penalty", "mute") == "mute":
        kb.append([InlineKeyboardButton(f"禁言时长: {s.get('mute_duration', 600) // 60}分钟", callback_data=f"spk_mute_{chat_id}", icon_custom_emoji_id="5776213190387961618")])
    kb.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(kb)


def get_mute_duration_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5分钟", callback_data=f"spk_setmute_{chat_id}_300"),
         InlineKeyboardButton("10分钟", callback_data=f"spk_setmute_{chat_id}_600")],
        [InlineKeyboardButton("30分钟", callback_data=f"spk_setmute_{chat_id}_1800"),
         InlineKeyboardButton("1小时", callback_data=f"spk_setmute_{chat_id}_3600")],
        [InlineKeyboardButton("« 返回", callback_data=f"spk_panel_{chat_id}")]
    ])


def get_penalty_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    kb = []
    for k, v in PENALTY_OPTIONS.items():
        kb.append([InlineKeyboardButton(v, callback_data=f"spk_setpenalty_{chat_id}_{k}")])
    kb.append([InlineKeyboardButton("« 返回", callback_data=f"spk_panel_{chat_id}")])
    return InlineKeyboardMarkup(kb)


async def speak_check_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    try:
        chat_id = int(data.split("_")[2])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception:
        return

    # 主面板
    if data.startswith("spk_panel_"):
        await query.answer()
        s = await database.get_message_check_settings(chat_id)
        await _show_panel(query, chat_id, s)
        return

    # 五项检查切换
    for key, cb_prefix in [("require_last_name", "spk_lastname_"), ("require_username", "spk_username_"),
                            ("require_photo", "spk_photo_"), ("require_premium", "spk_premium_"),
                            ("require_channel", "spk_channel_")]:
        if data.startswith(cb_prefix):
            s = await database.get_message_check_settings(chat_id)
            new_val = not s[key]
            await database.update_message_check_settings(chat_id, **{key: new_val})
            names = {"require_last_name": "姓氏", "require_username": "用户名", "require_photo": "头像",
                     "require_premium": "高级版", "require_channel": "订阅频道"}
            await query.answer(f'检查{names[key]}：{"开" if new_val else "关"}')
            s = await database.get_message_check_settings(chat_id)
            await _show_panel(query, chat_id, s)
            return

    # 设置频道 username
    if data.startswith("spk_setchannel_"):
        await query.answer()
        _AWAIT_SPEAK_CHANNEL[user_id] = chat_id
        _AWAIT_SPEAK_CHANNEL[f"{user_id}_conv"] = update.effective_chat.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"spk_panel_{chat_id}")]])
        await query.message.reply_html("请发送要检查的频道 @username 或频道 ID:", reply_markup=kb)
        return

    # 惩罚类型选择
    if data.startswith("spk_penalty_"):
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text="选择违反发言检查的惩罚方式：", reply_markup=get_penalty_keyboard(str(chat_id)))
        return

    if data.startswith("spk_setpenalty_"):
        parts = data.split("_")
        penalty = parts[-1]
        await database.update_message_check_settings(chat_id, penalty=penalty)
        await query.answer(f'惩罚已设为 {PENALTY_OPTIONS.get(penalty, penalty)}')
        await query.message.delete()
        s = await database.get_message_check_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SEARCH_EMOJI}">🔎</tg-emoji> <b>发言检查</b>',
            parse_mode="HTML", reply_markup=get_speak_check_keyboard(str(chat_id), s))
        return

    # 设置禁言时长
    if data.startswith("spk_mute_"):
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text="选择违反发言检查的禁言时长：", reply_markup=get_mute_duration_keyboard(str(chat_id)))
        return

    if data.startswith("spk_setmute_"):
        parts = data.split("_")
        seconds = int(parts[-1])
        await database.update_message_check_settings(chat_id, mute_duration=seconds)
        await query.answer(f'禁言时长已设为 {seconds // 60} 分钟')
        await query.message.delete()
        s = await database.get_message_check_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SEARCH_EMOJI}">🔎</tg-emoji> <b>发言检查</b>',
            parse_mode="HTML", reply_markup=get_speak_check_keyboard(str(chat_id), s))
        return


async def _show_panel(query, chat_id, s):
    text = (
        f'<tg-emoji emoji-id="{SEARCH_EMOJI}">🔎</tg-emoji> <b>发言检查</b>\n\n'
        f'检查姓氏: {"✅" if s["require_last_name"] else "❌"}\n'
        f'检查用户名: {"✅" if s["require_username"] else "❌"}\n'
        f'检查头像: {"✅" if s["require_photo"] else "❌"}\n'
        f'检查高级版: {"✅" if s["require_premium"] else "❌"}\n'
        f'检查订阅频道: {"✅" if s["require_channel"] else "❌"}'
    )
    if s.get("require_channel"):
        text += f'\n频道: @{s.get("channel_username") or "未设置"}'
    text += f'\n惩罚: {PENALTY_OPTIONS.get(s.get("penalty", "mute"), "禁言")}'
    if s.get("penalty", "mute") == "mute":
        text += f' {s.get("mute_duration", 600) // 60}分钟'
    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_speak_check_keyboard(str(chat_id), s))


_AWAIT_SPEAK_CHANNEL = {}


async def speak_check_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in _AWAIT_SPEAK_CHANNEL:
        return
    # 只消费在发起设置的同一会话里的消息，避免把其他会话的普通发言当成设置输入
    conv = _AWAIT_SPEAK_CHANNEL.get(f"{user_id}_conv")
    if conv is not None and (update.effective_chat is None or update.effective_chat.id != conv):
        return
    msg = update.message
    if not msg or not msg.text:
        return
    raw = msg.text.strip()
    chat_id = _AWAIT_SPEAK_CHANNEL.pop(user_id)
    _AWAIT_SPEAK_CHANNEL.pop(f"{user_id}_conv", None)
    await database.update_message_check_settings(chat_id, channel_username=raw.lstrip("@"))
    await msg.reply_html(f"✅ 订阅频道已设为 @{raw.lstrip('@')}")
    s = await database.get_message_check_settings(chat_id)
    await context.bot.send_message(chat_id=update.effective_chat.id,
        text=f'<tg-emoji emoji-id="{SEARCH_EMOJI}">🔎</tg-emoji> <b>发言检查</b>',
        parse_mode="HTML", reply_markup=get_speak_check_keyboard(str(chat_id), s))


# ── 消息拦截 ──────────────────────────────────────

async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检查发言条件，违反则处理，返回 True=已拦截"""
    msg = update.message
    if not msg:
        return False
    user = msg.from_user
    if not user or user.is_bot:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False

    s = await database.get_message_check_settings(chat.id)
    # 没有任何检查项开启则跳过
    if not any([s.get("require_last_name"), s.get("require_username"), s.get("require_photo"),
                s.get("require_premium"), s.get("require_channel")]):
        return False

    logger.info(f"speak_check: user={user.id} last_name={bool(user.last_name)} username={bool(user.username)} is_premium={getattr(user, 'is_premium', False)} settings={ {k: s.get(k) for k in ('require_last_name','require_username','require_photo','require_premium','require_channel')} }")
    violations = []

    # 1. 检查姓氏
    if s["require_last_name"] and not user.last_name:
        violations.append("未设置姓氏")

    # 2. 检查用户名
    if s["require_username"] and not user.username:
        violations.append("未设置用户名")

    # 3. 检查头像
    if s["require_photo"]:
        try:
            photos = await context.bot.get_user_profile_photos(user.id, limit=1)
            if not photos.photos:
                violations.append("未设置头像")
        except Exception:
            pass

    # 4. 检查高级版
    if s["require_premium"] and not getattr(user, "is_premium", False):
        violations.append("不是 Telegram 高级版用户")

    # 5. 检查订阅频道
    if s["require_channel"] and s["channel_username"]:
        ch = s["channel_username"]
        try:
            cm = await context.bot.get_chat_member(f"@{ch}" if not ch.startswith("-") else ch, user.id)
            if cm.status in ("left", "kicked", "restricted"):
                violations.append(f"未订阅 @{ch}")
        except Exception:
            violations.append(f"未订阅 @{ch}")

    if not violations:
        return False

    # 删除消息
    try:
        await msg.delete()
    except Exception:
        pass

    penalty = s.get("penalty", "mute")
    reasons = "、".join(violations)
    try:
        if penalty == "ban":
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            warn_text = f"{WARN_EMOJI} {user.mention_html()} 已被封禁\n原因：{reasons}"
        elif penalty == "kick":
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            await context.bot.unban_chat_member(chat_id=chat.id, user_id=user.id)
            warn_text = f"{WARN_EMOJI} {user.mention_html()} 已被踢出\n原因：{reasons}"
        else:
            mute_sec = s["mute_duration"]
            until = datetime.utcnow() + timedelta(seconds=mute_sec)
            await context.bot.restrict_chat_member(
                chat_id=chat.id, user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            warn_text = f"{WARN_EMOJI} {user.mention_html()} 发言已被拦截\n原因：{reasons}\n禁言 {mute_sec // 60} 分钟"
    except Exception as e:
        warn_text = f"{WARN_EMOJI} {user.mention_html()} 违规但惩罚失败: {e}"

    try:
        warn_msg = await context.bot.send_message(
            chat_id=chat.id, text=warn_text, parse_mode="HTML"
        )
        asyncio.create_task(_del_warn(context.bot, chat.id, warn_msg.message_id, s.get("warn_delete", 30)))
    except Exception:
        pass

    return True


async def _del_warn(bot, chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
