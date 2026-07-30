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

LABELS = {
    "block_contact": "屏蔽联系人卡片", "block_location": "屏蔽位置信息",
    "block_channel_send": "屏蔽频道马甲", "block_channel_fwd": "屏蔽频道转发",
    "block_external_ref": "屏蔽外部引用", "block_exe": "屏蔽EXE",
    "block_mention": "屏蔽@用户", "block_links": "屏蔽所有链接",
    "block_long_links": "屏蔽超长链接",
    "block_flood": "屏蔽刷屏",
}


def get_antispam_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    def _icon(key): return CHECK_EMOJI if s[key] else CROSS_EMOJI
    _cb_map = {
        "block_contact": "contact", "block_location": "location",
        "block_channel_send": "chsend", "block_channel_fwd": "chfwd",
        "block_external_ref": "extref", "block_exe": "exe", "block_mention": "mention",
        "block_links": "links", "block_long_links": "longlinks",
        "block_flood": "flood",
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
        chat_id = int(data.split("_")[-1])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("as_panel_"):
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

    # 白名单管理
    if data.startswith("as_whitelist_"):
        await query.answer()
        s = await database.get_antispam_settings(chat_id)
        wl = _parse_whitelist(s["whitelist"])
        wl_text = "\n".join(f"· {uid}" for uid in wl) if wl else "空"
        text = f"<b>白名单</b>（{len(wl)}人）\n\n{wl_text}\n\n发送用户ID添加，发送 <code>del ID</code> 删除"
        _AWAIT_ANTISPAM[user_id] = chat_id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
        return

    # 禁言时长
    if data.startswith("as_mutedur_"):
        await query.answer()
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_field"] = "mute_duration"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.message.reply_html("请发送禁言时长（分钟）：", reply_markup=kb)
        return

    # 刷屏阈值
    if data.startswith("as_floodset_"):
        await query.answer()
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_field"] = "flood"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.message.reply_html("请发送刷屏阈值，格式：<code>条数|秒数</code>\n示例：<code>5|10</code>（10秒内5条）", reply_markup=kb)
        return

    # 刷屏参数
    if data.startswith("as_warndel_"):
        await query.answer()
        _AWAIT_ANTISPAM[user_id] = chat_id
        _AWAIT_ANTISPAM[f"{user_id}_field"] = "warn_delete"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=f"as_panel_{chat_id}")]])
        await query.message.reply_html("请发送提示消息删除时间（秒）：", reply_markup=kb)
        return


async def antispam_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    field = _AWAIT_ANTISPAM.pop(f"{user_id}_field", None)
    chat_id = _AWAIT_ANTISPAM.pop(user_id, None)
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

_URL_RE = re.compile(r"https?://\S+", re.I)
_LONG_URL_RE = re.compile(r"https?://\S{50,}", re.I)


async def check_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回 (是否拦截, 原因)"""
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
        "block_long_links", "block_flood"])
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

    # 8. 所有链接
    if s["block_links"] and msg.text and _URL_RE.search(msg.text):
        return True, "链接"

    # 9. 超长链接
    if s["block_long_links"] and msg.text and _LONG_URL_RE.search(msg.text):
        return True, "超长链接"

    # 10. 刷屏检测
    if s["block_flood"] and msg.text:
        now = time.monotonic()
        tracker = _flood_tracker[chat.id][user.id]
        text = msg.text.strip()
        tracker.append((now, text))
        # 清理超时记录
        cutoff = now - s["flood_timeout"]
        tracker[:] = [(t, txt) for t, txt in tracker if t > cutoff]
        # 检查相同消息计数
        same_count = sum(1 for _, txt in tracker if txt == text)
        if same_count >= s["flood_count"]:
            tracker.clear()
            return True, f"刷屏 ({same_count}条相同消息/{s['flood_timeout']}s)"

    return False, ""


async def antispam_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """拦截消息：删除 + 惩罚 + 警告"""
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
