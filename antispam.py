import asyncio
import logging
import re
import time
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
import database
from database import validate_column_name

logger = logging.getLogger(__name__)
logger.info("antispam module loaded")

CHECK_EMOJI = "5776375003280838798"
CROSS_EMOJI = "5778527486270770928"
WARN_EMOJI_ID = "5447644880824181073"
SETTINGS_EMOJI = "5931409969613116639"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'

PENALTY_OPTIONS = {"delete": "仅删除", "mute": "禁言", "kick": "踢出", "ban": "封禁"}

# 刷屏追踪: chat_id → {user_id: [(timestamp, text), ...]}
_flood_tracker = defaultdict(lambda: defaultdict(list))
_AWAIT_ANTISPAM = {}

# @ 访客机器人追踪: chat_id → {caller_user_id: [(msg_id, bot_username, timestamp), ...]}
# 用于在访客机器人发言后回溯删除调用者 @ 它的那条消息
_mention_tracker = defaultdict(lambda: defaultdict(list))

_MENTION_WINDOW = 10  # 回溯删除的匹配窗口(秒)


def record_bot_mentions(update: Update):
    """记录群里普通用户 @ 机器人 的消息, 供访客机器人发言时回溯删除。

    只记录 mention/text_mention 指向 bot 用户名的那条消息的 message_id,
    关联调用者 user_id。10 秒窗口内若有访客机器人发言, 按 username 匹配删除。
    """
    msg = update.message
    if not msg:
        return
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    caller = msg.from_user
    if not caller or caller.is_bot:
        return
    entities = list(msg.entities or []) + list(msg.caption_entities or [])
    if not entities:
        return
    content = msg.text or msg.caption or ""
    now = time.monotonic()
    for ent in entities:
        target = None
        if ent.type == "mention":
            # @username 直接写在文本里
            target = content[ent.offset:ent.offset + ent.length].lstrip("@")
        elif ent.type == "text_mention":
            u = getattr(ent, "user", None)
            if u is not None and u.is_bot and getattr(u, "username", None):
                target = u.username
        if target:
            _mention_tracker[chat.id][caller.id].append((msg.message_id, target.lower(), now))
    # 就地清理当前 chat 的过期条目, 避免依赖 24h 定时器、防止内存膨胀
    _prune_mentions_for_chat(chat.id, now)


def _prune_mentions_for_chat(chat_id, now=None):
    """裁剪指定 chat 里超出窗口的 @ 追踪条目。"""
    if now is None:
        now = time.monotonic()
    chat_trackers = _mention_tracker.get(chat_id)
    if not chat_trackers:
        return
    for user_id in list(chat_trackers.keys()):
        lst = chat_trackers[user_id]
        lst[:] = [(mid, uname, t) for mid, uname, t in lst if now - t <= _MENTION_WINDOW]
        if not lst:
            chat_trackers.pop(user_id, None)
    if not chat_trackers:
        _mention_tracker.pop(chat_id, None)


def cleanup_mention_tracker():
    """清理 @ 追踪里过期的条目, 防止内存无限增长。"""
    now = time.monotonic()
    for chat_id in list(_mention_tracker.keys()):
        chat_trackers = _mention_tracker[chat_id]
        for user_id in list(chat_trackers.keys()):
            lst = chat_trackers[user_id]
            lst[:] = [(mid, uname, t) for mid, uname, t in lst if now - t <= _MENTION_WINDOW]
            if not lst:
                chat_trackers.pop(user_id, None)
        if not chat_trackers:
            _mention_tracker.pop(chat_id, None)


async def _delete_caller_mention_msg(context, chat_id, caller_id, bot_username):
    """删除调用者 @ 该访客机器人的原始消息。

    根据 caller_id + 访客机器人 username 在 _mention_tracker 里匹配,
    命中则删除对应 message_id。访客机器人 update 不带调用者消息 ID,
    但 @ 消息本身真实存在于群里, 通过记录+匹配即可定位。
    """
    try:
        caller_trackers = _mention_tracker.get(chat_id, {}).get(caller_id)
        if not caller_trackers:
            return
        uname = (bot_username or "").lower()
        if not uname:
            return
        now = time.monotonic()
        matched = []
        keep = []
        for mid, m_uname, t in caller_trackers:
            if now - t <= _MENTION_WINDOW and m_uname == uname:
                matched.append(mid)
            else:
                keep.append((mid, m_uname, t))
        # 只保留未命中的条目
        if keep:
            _mention_tracker[chat_id][caller_id] = keep
        else:
            _mention_tracker[chat_id].pop(caller_id, None)
            if not _mention_tracker[chat_id]:
                _mention_tracker.pop(chat_id, None)
        for mid in matched:
            await _delete_caller_message(context, chat_id, mid)
    except Exception:
        pass


async def _delete_caller_message(context, chat_id, msg_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


def cleanup_flood_tracker():
    """清理刷屏追踪里过期/空的条目, 防止 _flood_tracker 内存无限增长。

    每次刷屏检测只清理"当前用户"的过期记录; 一次性用户留下的空键
    需要周期调用本函数统一清掉, 让 tracker 只保留最近一段时间的活跃记录。
    """
    now = time.monotonic()
    for chat_id in list(_flood_tracker.keys()):
        chat_trackers = _flood_tracker[chat_id]
        for user_id in list(chat_trackers.keys()):
            lst = chat_trackers[user_id]
            # 兜底保留窗口: 超过 1 小时的记录直接丢弃
            lst[:] = [(t, txt) for t, txt in lst if now - t <= 3600]
            if not lst:
                chat_trackers.pop(user_id, None)
        if not chat_trackers:
            _flood_tracker.pop(chat_id, None)

LABELS = {
    "block_contact": "屏蔽联系人卡片", "block_location": "屏蔽位置信息",
    "block_channel_send": "屏蔽频道马甲", "block_channel_fwd": "屏蔽频道转发",
    "block_external_ref": "屏蔽外部引用", "block_exe": "屏蔽EXE",
    "block_mention": "屏蔽@用户", "block_links": "屏蔽所有链接",
    "block_long_links": "屏蔽超长链接",
    "block_flood": "屏蔽刷屏",
    "block_visitor_bots": "拦截访客机器人",
}


def get_antispam_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    def _icon(key): return CHECK_EMOJI if s[key] else CROSS_EMOJI
    _cb_map = {
        "block_contact": "contact", "block_location": "location",
        "block_channel_send": "chsend", "block_channel_fwd": "chfwd",
        "block_external_ref": "extref", "block_exe": "exe", "block_mention": "mention",
        "block_links": "links", "block_long_links": "longlinks",
        "block_flood": "flood", "block_visitor_bots": "visitor",
    }
    kb_rows = []
    for key, cb in _cb_map.items():
        label = LABELS.get(key, key)
        if key == "block_flood":
            label = f'{label} ({s["flood_count"]}条/{s["flood_timeout"]}s)'
        kb_rows.append([InlineKeyboardButton(label, callback_data=f"as_{cb}_{chat_id}", icon_custom_emoji_id=_icon(key))])
    kb = InlineKeyboardMarkup(
        kb_rows + [
        [InlineKeyboardButton(f"刷屏阈值: {s['flood_count']}条/{s['flood_timeout']}s", callback_data=f"as_floodset_{chat_id}")],
        [InlineKeyboardButton(f'惩罚: {PENALTY_OPTIONS.get(s["penalty"], s["penalty"])}', callback_data=f"as_penalty_{chat_id}")],
        [InlineKeyboardButton("访客机器人处罚设置", callback_data=f"as_visitorpen_{chat_id}")],
        [InlineKeyboardButton(f'禁言时长: {s.get("mute_duration", 3600) // 60}分钟', callback_data=f"as_mutedur_{chat_id}")],
        [InlineKeyboardButton(f'白名单 ({len(_parse_whitelist(s["whitelist"]))}人)', callback_data=f"as_whitelist_{chat_id}")],
        [InlineKeyboardButton(f'提示删除: {s["warn_delete"]}s', callback_data=f"as_warndel_{chat_id}")],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]
    ])
    return kb


def _parse_whitelist(raw: str) -> list:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


async def antispam_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    try:
        parts = data.split("_")
        # chat_id 通常在末尾; as_setpen_{chat_id}_{penalty} 里 chat_id 在倒数第二
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

    if data.startswith("as_panel_"):
        # 用户通过“返回”离开设置流程，清除挂起的输入等待状态
        _AWAIT_ANTISPAM.pop(user_id, None)
        _AWAIT_ANTISPAM.pop(f"{user_id}_field", None)
        _AWAIT_ANTISPAM.pop(f"{user_id}_conv", None)
        await query.answer()
        s = await database.get_antispam_settings(chat_id)
        text = f'<tg-emoji emoji-id="{SETTINGS_EMOJI}">⚙️</tg-emoji> <b>反垃圾</b>\n\n刷屏: {s["flood_count"]}条/{s["flood_timeout"]}s\n惩罚: {PENALTY_OPTIONS.get(s["penalty"])}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_antispam_keyboard(str(chat_id), s))
        return

    # 各项屏蔽
    key_map = {
        "as_contact_": "block_contact", "as_location_": "block_location",
        "as_chsend_": "block_channel_send", "as_chfwd_": "block_channel_fwd",
        "as_extref_": "block_external_ref", "as_exe_": "block_exe",
        "as_mention_": "block_mention", "as_links_": "block_links",
        "as_longlinks_": "block_long_links",
        "as_flood_": "block_flood",
        "as_visitor_": "block_visitor_bots",
    }
    for prefix, key in key_map.items():
        if data.startswith(prefix):
            s = await database.get_antispam_settings(chat_id)
            await database.update_antispam_settings(chat_id, **{key: not s[key]})
            await query.answer(f'{LABELS.get(key, key)}: {"开" if not s[key] else "关"}')
            s = await database.get_antispam_settings(chat_id)
            await query.edit_message_reply_markup(reply_markup=get_antispam_keyboard(str(chat_id), s))
            return

    # 惩罚设置
    if data.startswith("as_penalty_"):
        await query.answer()
        kb = []
        for k, v in PENALTY_OPTIONS.items():
            kb.append([InlineKeyboardButton(v, callback_data=f"as_setpen_{chat_id}_{k}")])
        kb.append([InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")])
        await query.edit_message_text("选择触发惩罚：", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("as_setpen_"):
        penalty = data.split("_")[-1]
        await database.update_antispam_settings(chat_id, penalty=penalty)
        await query.answer(f'惩罚已设为 {PENALTY_OPTIONS.get(penalty, penalty)}')
        s = await database.get_antispam_settings(chat_id)
        text = f'<tg-emoji emoji-id="{SETTINGS_EMOJI}">⚙️</tg-emoji> <b>反垃圾</b>\n\n功能: {"开" if s["enabled"] else "关"}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_antispam_keyboard(str(chat_id), s))
        return

    # 访客机器人处罚设置（子菜单）
    if data.startswith("as_visitorpen_"):
        await query.answer()
        s = await database.get_antispam_settings(chat_id)
        bot_pen = s.get("visitor_bot_penalty", "ban")
        caller_pen = s.get("visitor_caller_penalty", "delete")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f'访客机器人处罚: {PENALTY_OPTIONS.get(bot_pen, bot_pen)}', callback_data=f"as_vbotpen_{chat_id}")],
            [InlineKeyboardButton(f'调用者处罚: {PENALTY_OPTIONS.get(caller_pen, caller_pen)}', callback_data=f"as_vcallerpen_{chat_id}")],
            [InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")],
        ])
        await query.edit_message_text("设置访客机器人的处罚方式：", reply_markup=kb)
        return

    if data.startswith("as_vbotpen_"):
        await query.answer()
        s = await database.get_antispam_settings(chat_id)
        cur = s.get("visitor_bot_penalty", "ban")
        kb = []
        for k, v in PENALTY_OPTIONS.items():
            kb.append([InlineKeyboardButton(v, callback_data=f"as_setvbotpen_{chat_id}_{k}")])
        kb.append([InlineKeyboardButton("« 返回", callback_data=f"as_visitorpen_{chat_id}")])
        await query.edit_message_text(f"选择访客机器人处罚方式（当前：{PENALTY_OPTIONS.get(cur, cur)}）：", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("as_setvbotpen_"):
        penalty = data.split("_")[-1]
        await database.update_antispam_settings(chat_id, visitor_bot_penalty=penalty)
        await query.answer(f'访客机器人处罚已设为 {PENALTY_OPTIONS.get(penalty, penalty)}')
        s = await database.get_antispam_settings(chat_id)
        bot_pen = s.get("visitor_bot_penalty", "ban")
        caller_pen = s.get("visitor_caller_penalty", "delete")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f'访客机器人处罚: {PENALTY_OPTIONS.get(bot_pen, bot_pen)}', callback_data=f"as_vbotpen_{chat_id}")],
            [InlineKeyboardButton(f'调用者处罚: {PENALTY_OPTIONS.get(caller_pen, caller_pen)}', callback_data=f"as_vcallerpen_{chat_id}")],
            [InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")],
        ])
        await query.edit_message_text("设置访客机器人的处罚方式：", reply_markup=kb)
        return

    if data.startswith("as_vcallerpen_"):
        await query.answer()
        s = await database.get_antispam_settings(chat_id)
        cur = s.get("visitor_caller_penalty", "delete")
        kb = []
        for k, v in PENALTY_OPTIONS.items():
            kb.append([InlineKeyboardButton(v, callback_data=f"as_setvcallerpen_{chat_id}_{k}")])
        kb.append([InlineKeyboardButton("« 返回", callback_data=f"as_visitorpen_{chat_id}")])
        await query.edit_message_text(f"选择调用者处罚方式（当前：{PENALTY_OPTIONS.get(cur, cur)}）：", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("as_setvcallerpen_"):
        penalty = data.split("_")[-1]
        await database.update_antispam_settings(chat_id, visitor_caller_penalty=penalty)
        await query.answer(f'调用者处罚已设为 {PENALTY_OPTIONS.get(penalty, penalty)}')
        s = await database.get_antispam_settings(chat_id)
        bot_pen = s.get("visitor_bot_penalty", "ban")
        caller_pen = s.get("visitor_caller_penalty", "delete")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f'访客机器人处罚: {PENALTY_OPTIONS.get(bot_pen, bot_pen)}', callback_data=f"as_vbotpen_{chat_id}")],
            [InlineKeyboardButton(f'调用者处罚: {PENALTY_OPTIONS.get(caller_pen, caller_pen)}', callback_data=f"as_vcallerpen_{chat_id}")],
            [InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")],
        ])
        await query.edit_message_text("设置访客机器人的处罚方式：", reply_markup=kb)
        return

    # 白名单管理
    if data.startswith("as_whitelist_"):
        await query.answer()
        s = await database.get_antispam_settings(chat_id)
        wl = _parse_whitelist(s["whitelist"])
        wl_text = "\n".join(f"· {uid}" for uid in wl) if wl else "空"
        text = f"<b>白名单</b>（{len(wl)}人）\n\n{wl_text}\n\n发送用户ID添加，发送 <code>del ID</code> 删除"
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_conv"] = update.effective_chat.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
        return

    # 禁言时长
    if data.startswith("as_mutedur_"):
        await query.answer()
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_conv"] = update.effective_chat.id
        _AWAIT_ANTISPAM[f"{user_id}_field"] = "mute_duration"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.message.reply_html("请发送禁言时长（分钟）：", reply_markup=kb)
        return

    # 刷屏阈值
    if data.startswith("as_floodset_"):
        await query.answer()
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_conv"] = update.effective_chat.id
        _AWAIT_ANTISPAM[f"{user_id}_field"] = "flood"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.message.reply_html("请发送刷屏阈值，格式：<code>条数|秒数</code>\n示例：<code>5|10</code>（10秒内5条）", reply_markup=kb)
        return

    # 刷屏参数
    if data.startswith("as_warndel_"):
        await query.answer()
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_conv"] = update.effective_chat.id
        _AWAIT_ANTISPAM[f"{user_id}_field"] = "warn_delete"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.message.reply_html("请发送提示消息删除时间（秒）：", reply_markup=kb)
        return


async def antispam_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # 只消费在发起设置的同一会话里的消息，避免把其他会话的普通发言当成设置输入
    conv = _AWAIT_ANTISPAM.get(f"{user_id}_conv")
    if conv is not None and (update.effective_chat is None or update.effective_chat.id != conv):
        return
    field = _AWAIT_ANTISPAM.pop(f"{user_id}_field", None)
    chat_id = _AWAIT_ANTISPAM.pop(user_id, None)
    _AWAIT_ANTISPAM.pop(f"{user_id}_conv", None)
    if not chat_id:
        return

    msg = update.message
    if not msg or not msg.text:
        return
    raw = msg.text.strip()

    if field == "warn_delete":
        try:
            await database.update_antispam_settings(chat_id, warn_delete=int(raw))
            await msg.reply_html(f"{EMOJI_SUCCESS} 已设置")
        except Exception:
            await msg.reply_html(f"{EMOJI_WARN} 请输入数字")
        return

    if field == "flood":
        try:
            parts = raw.split("|")
            cnt = int(parts[0])
            sec = int(parts[1])
            if cnt < 2 or sec < 3:
                raise ValueError
            await database.update_antispam_settings(chat_id, flood_count=cnt, flood_timeout=sec)
            await msg.reply_html(f"{EMOJI_SUCCESS} 刷屏阈值已设为 {cnt}条/{sec}s")
        except Exception:
            await msg.reply_html(f"{EMOJI_WARN} 格式错误，请用 条数|秒数，如 5|10")
        return

    if field == "mute_duration":
        try:
            mins = int(raw)
            await database.update_antispam_settings(chat_id, mute_duration=mins * 60)
            await msg.reply_html(f"{EMOJI_SUCCESS} 禁言时长已设为 {mins} 分钟")
        except Exception:
            await msg.reply_html(f"{EMOJI_WARN} 请输入数字")
        return

    # 白名单: del ID 或 直接加 ID
    if raw.startswith("del "):
        uid = int(raw[4:].strip())
        s = await database.get_antispam_settings(chat_id)
        wl = _parse_whitelist(s["whitelist"])
        if uid in wl:
            wl.remove(uid)
        await database.update_antispam_settings(chat_id, whitelist=",".join(str(x) for x in wl))
        await msg.reply_html(f"{EMOJI_SUCCESS} 已从白名单移除 {uid}")
    else:
        try:
            uid = int(raw)
            s = await database.get_antispam_settings(chat_id)
            wl = _parse_whitelist(s["whitelist"])
            if uid not in wl:
                wl.append(uid)
            await database.update_antispam_settings(chat_id, whitelist=",".join(str(x) for x in wl))
            await msg.reply_html(f"{EMOJI_SUCCESS} 已添加 {uid} 到白名单")
        except Exception:
            await msg.reply_html(f"{EMOJI_WARN} 请输入有效用户ID 或 del ID")


# ── 消息拦截 ──────────────────────────────────────

_URL_RE = re.compile(r"(?:https?://|www\.)\S+|t\.me\b", re.I)
_LONG_URL_RE = re.compile(r"(?:https?://|www\.|t\.me\b)\S{50,}", re.I)


async def visitor_bot_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """拦截访客机器人发言。

    访客机器人(Guest Bot)在群里发言时, Message 会携带 guest_bot_caller_user /
    guest_bot_caller_chat / guest_query_id 字段, 可据此识别并拿到调用者身份。
    """
    msg = update.message
    if not msg:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    user = msg.from_user
    # 只针对机器人发言; 且必须携带访客机器人标记
    if not user or not user.is_bot:
        return False
    caller = getattr(msg, "guest_bot_caller_user", None)
    if caller is None:
        return False

    s = await database.get_antispam_settings(chat.id)
    if not s.get("block_visitor_bots"):
        return False

    bot_id = user.id
    caller_id = caller.id if hasattr(caller, "id") else None

    # 删除访客机器人消息
    try:
        await msg.delete()
    except Exception:
        pass

    # 分别处罚：访客机器人 + 调用者
    bot_pen = s.get("visitor_bot_penalty", "ban")
    caller_pen = s.get("visitor_caller_penalty", "delete")
    # 访客机器人的发言已在上方 msg.delete() 删除; 其余处罚走 _apply_penalty
    if bot_pen != "delete":
        await _apply_penalty(context, chat.id, bot_id, bot_pen, s)
    if caller_id is not None:
        if caller_pen == "delete":
            await _delete_caller_mention_msg(context, chat.id, caller_id, user.username)
        else:
            await _apply_penalty(context, chat.id, caller_id, caller_pen, s)

    # 警告提示
    try:
        warn_msg = await context.bot.send_message(
            chat.id,
            f'<tg-emoji emoji-id="{WARN_EMOJI_ID}">⚠️</tg-emoji> 检测到访客机器人发言，已拦截\n'
            f'访客机器人: <code>{bot_id}</code>（{PENALTY_OPTIONS.get(bot_pen, bot_pen)}）\n'
            f'调用者: <code>{caller_id}</code>（{PENALTY_OPTIONS.get(caller_pen, caller_pen)}）',
            parse_mode="HTML"
        )
        asyncio.create_task(_del_warn(context.bot, chat.id, warn_msg.message_id, s["warn_delete"]))
    except Exception:
        pass

    return True


async def _apply_penalty(context, chat_id, user_id, penalty, s):
    """按指定处罚方式处理单个用户，失败静默。"""
    if penalty == "mute":
        try:
            from datetime import datetime, timedelta
            dur = s.get("mute_duration", 3600)
            until = datetime.utcnow() + timedelta(seconds=dur)
            await context.bot.restrict_chat_member(chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False), until_date=until)
        except Exception:
            pass
    elif penalty == "kick":
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id)
        except Exception:
            pass
    elif penalty == "ban":
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
        except Exception:
            pass


async def check_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return False, ""
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False, ""
    user = msg.from_user
    if not user or user.is_bot:
        return False, ""

    s = await database.get_antispam_settings(chat.id)
    # 没有任何屏蔽项开启则跳过
    has_any = any(s.get(k) for k in [
        "block_contact", "block_location", "block_channel_send", "block_channel_fwd",
        "block_external_ref", "block_exe", "block_mention", "block_links",
        "block_long_links", "block_flood", "block_visitor_bots"])
    if not has_any:
        return False, ""
    # debug log
    logger.info(f"antispam: user={user.id} contact={bool(msg.contact)} location={bool(msg.location or msg.venue)} text={str(msg.text)[:50] if msg.text else ''} settings={ {k: s.get(k) for k in ('block_contact','block_location','block_links','block_flood')} }")

    wl = _parse_whitelist(s["whitelist"])
    if user.id in wl:
        return False, ""

    # 1. 联系人卡片
    if s["block_contact"] and msg.contact:
        return True, "联系人卡片"

    # 2. 位置
    if s["block_location"] and (msg.location or msg.venue):
        return True, "位置信息"

    # 3. 频道马甲 (sender_chat)
    if s["block_channel_send"] and msg.sender_chat:
        return True, "频道马甲发言"

    # 4. 频道转发 (forward_from_chat / forward_from_message_id)
    if s["block_channel_fwd"] and (msg.forward_from_chat or msg.forward_from_message_id):
        if msg.forward_from_chat and msg.forward_from_chat.type == "channel":
            return True, "频道转发"
        if msg.forward_from_chat and msg.forward_from_chat.type in ("group", "supergroup"):
            pass  # 群转发不拦

    # 5. 外部引用
    if s["block_external_ref"] and msg.external_reply:
        return True, "外部引用"

    # 6. EXE 文件
    if s["block_exe"] and msg.document:
        fn = msg.document.file_name or ""
        if fn.lower().endswith((".exe", ".apk", ".bat", ".sh", ".msi", ".dmg")):
            return True, "可执行文件"

    # 7. @ 用户过多
    if s["block_mention"] and msg.entities:
        mentions = sum(1 for e in msg.entities if e.type in ("mention", "text_mention"))
        if mentions > 3:
            return True, f"过多@ ({mentions}个)"

    # 8. 所有链接 — 优先按 Telegram 打的 url/text_link 实体拦截, 正则兜底
    if s["block_links"]:
        content = msg.text or msg.caption or ""
        # text_link(锚文本隐藏URL) / url(文本即URL) 实体, 只要是 Telegram 识别的链接就拦
        ents = list(msg.entities or []) + list(msg.caption_entities or [])
        for ent in ents:
            if ent.type == "text_link" and getattr(ent, "url", None):
                return True, "链接"
            if ent.type == "url":
                return True, "链接"
        # 兜底: 文本正则, 覆盖 Telegram 没打实体但包含链接形态的文本
        if _URL_RE.search(content):
            return True, "链接"
        # Markdown 隐藏链裸文本： [锚文本](URL) 或 (URL)
        if re.search(r"\]\s*\(\s*\S+://\S+", content) or re.search(r"\(\s*(?:https?://|www\.|t\.me\b)\S+", content):
            return True, "链接"

    # 9. 超长链接 — 同样覆盖 text / caption / 内嵌 entity
    if s["block_long_links"]:
        content = msg.text or msg.caption or ""
        if _LONG_URL_RE.search(content):
            return True, "超长链接"
        for ent in list(msg.entities or []) + list(msg.caption_entities or []):
            if ent.type == "text_link" and ent.url and _LONG_URL_RE.search(ent.url):
                return True, "超长链接"

    # 10. 刷屏检测
    if s["block_flood"] and msg.text:
        now = time.monotonic()
        chat_trackers = _flood_tracker[chat.id]
        tracker = chat_trackers[user.id]
        text = msg.text.strip()
        tracker.append((now, text))
        # 清理超时记录
        cutoff = now - s["flood_timeout"]
        tracker[:] = [(t, txt) for t, txt in tracker if t > cutoff]
        # 检查相同消息计数
        same_count = sum(1 for _, txt in tracker if txt == text)
        hit = same_count >= s["flood_count"]
        # 命中或记录已全过期 → 删掉空条目, 防止 _flood_tracker 无限膨胀
        if hit or not tracker:
            chat_trackers.pop(user.id, None)
            if not chat_trackers:
                _flood_tracker.pop(chat.id, None)
        if hit:
            return True, f"刷屏 ({same_count}条相同消息/{s['flood_timeout']}s)"

    return False, ""


async def antispam_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blocked, reason = await check_antispam(update, context)
    if not blocked:
        return False

    msg = update.message
    chat = update.effective_chat
    user = msg.from_user

    s = await database.get_antispam_settings(chat.id)
    penalty = s["penalty"]

    # 删除
    try:
        await msg.delete()
    except Exception:
        pass

    # 惩罚
    if penalty == "mute":
        try:
            from datetime import datetime, timedelta
            dur = s.get("mute_duration", 3600)
            until = datetime.utcnow() + timedelta(seconds=dur)
            await context.bot.restrict_chat_member(chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False), until_date=until)
        except Exception:
            pass
    elif penalty == "kick":
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            await context.bot.unban_chat_member(chat.id, user.id)
        except Exception:
            pass
    elif penalty == "ban":
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
        except Exception:
            pass

    # 警告
    try:
        warn_msg = await context.bot.send_message(
            chat.id,
            f'<tg-emoji emoji-id="{WARN_EMOJI_ID}">⚠️</tg-emoji> {user.mention_html()} 消息被拦截\n原因：{reason}',
            parse_mode="HTML"
        )
        asyncio.create_task(_del_warn(context.bot, chat.id, warn_msg.message_id, s["warn_delete"]))
    except Exception:
        pass

    return True


async def _del_warn(bot, chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
