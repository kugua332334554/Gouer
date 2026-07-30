import asyncio
import logging
import re
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
import config
import database
import payment
from database import validate_column_name
import plugin_bridge as _pb
def _p(fn): return getattr(_pb.get("ai_plugin"), fn)
ai_chat = lambda *a,**k: _p("chat")(*a,**k)
ai_stream = lambda *a,**k: _p("chat_stream")(*a,**k)
async def generate_fortune(*a,**k): return await _p("generate_fortune")(*a,**k)

logger = logging.getLogger(__name__)
logger.info("ai module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
ADD_EMOJI_ID = "5775937998948404844"
BACK_EMOJI_ID = "5875082500023258804"
DELETE_EMOJI_ID = "6017288111279575194"
ROBOT_EMOJI_ID = "5931409969613116639"
WARN_EMOJI_ID = "5447644880824181073"
TEXT_EMOJI_ID = "5879895758202735862"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'

DEFAULT_PROMPT = (
    "你是狗经理，一个网络安全社区的 AI 助手，身份是资深渗透测试工程师。\n"
    "你的口头禅：在在在，狗经理 24×7 在线，漏洞不停我不下班。\n"
    "说话风格：幽默、毒舌、接地气，会用网络安全黑话和梗。\n"
    "如果有人问感情或修电脑，回复：狗经理只懂社工不修电脑。\n"
    "如果有人问你是谁创造的，回复：我老大是 TGSEC 网络安全社区。\n"
    "回答简短，不超过100字。\n\n"
    "【格式规则 必须遵守】\n"
    "每条回复必须至少包含一个 {tz} 贴纸\n"
    "发骰子写 {dice:dart} 不要写 {dc}\n"
    "发贴纸写 {tz:👍}\n"
    "骰子类型: dice(🎲) dart(🎯) basketball(🏀) football(⚽) slot(🎰)"
)

_AWAIT_AI_INPUT = {}

PENALTY_OPTIONS = {"delete": "仅删除", "mute_1h": "禁言1小时", "kick": "踢出", "ban": "封禁"}


def parse_triggers(trigger_str: str) -> list:
    if not trigger_str or not trigger_str.strip():
        return []
    return [t.strip() for t in trigger_str.split(",") if t.strip()]


def join_triggers(triggers: list) -> str:
    return ", ".join(triggers)


def message_has_trigger(text: str, triggers: list) -> bool:
    if not triggers:
        return False
    return any(text.startswith(t) for t in triggers)


def get_triggered_prompt(text: str, triggers: list) -> tuple:
    if not triggers:
        return None, None
    for t in sorted(triggers, key=len, reverse=True):
        if text.startswith(t):
            return t, text[len(t):].strip()
    return None, None


async def get_ai_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, chat_enabled, chat_prompt, chat_trigger, audit_enabled, audit_penalty FROM group_ai WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"chat_id": row[0], "chat_enabled": bool(row[1]), "chat_prompt": row[2] or DEFAULT_PROMPT,
                            "chat_trigger": row[3] or "", "audit_enabled": bool(row[4]), "audit_penalty": row[5] or "delete"}
    except Exception:
        pass
    return {"chat_id": chat_id, "chat_enabled": False, "chat_prompt": DEFAULT_PROMPT, "chat_trigger": "", "audit_enabled": False, "audit_penalty": "delete"}


async def update_ai_settings(chat_id: int, **kwargs):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_ai (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_ai SET {', '.join(parts)} WHERE chat_id = %s", vals)
    except Exception as e:
        logger.error(f"update_ai_settings err: {e}")


def get_ai_keyboard(chat_id: str, settings: dict, lang: str = "zh") -> InlineKeyboardMarkup:
    from lang import t_sync
    chat_status = t_sync(lang, "enable") if settings["chat_enabled"] else t_sync(lang, "disable")
    audit_status = t_sync(lang, "enable") if settings["audit_enabled"] else t_sync(lang, "disable")
    trigger = settings["chat_trigger"] or t_sync(lang, "unknown")
    triggers = parse_triggers(trigger)
    trigger_display = ", ".join(triggers[:3]) + ("…" if len(triggers) > 3 else "") if triggers else t_sync(lang, "unknown")
    penalty_map = {"delete": t_sync(lang, "ai_delete_only"), "mute_1h": t_sync(lang, "ai_mute_1h"), "kick": t_sync(lang, "ai_kick"), "ban": t_sync(lang, "ai_ban")}
    price_text = f"购买AI审查订阅 ({config.AI_PRICE} {config.AI_CURRENCY})"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(price_text, callback_data=f"ai_buy_{chat_id}", icon_custom_emoji_id="6044023213250319833")],
        [InlineKeyboardButton(f'{t_sync(lang, "ai_chat_label")} {chat_status}', callback_data=f"ai_togglechat_{chat_id}", icon_custom_emoji_id=CHECK_EMOJI_ID if settings["chat_enabled"] else CROSS_EMOJI_ID)],
        [InlineKeyboardButton(f'{t_sync(lang, "ai_trigger_label")} {trigger_display[:20]}', callback_data=f"ai_settrigger_{chat_id}", icon_custom_emoji_id=TEXT_EMOJI_ID)],
        [InlineKeyboardButton(t_sync(lang, "ai_set_prompt_btn"), callback_data=f"ai_setprompt_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID)],
        [InlineKeyboardButton(f'{t_sync(lang, "ai_audit_label")} {audit_status}', callback_data=f"ai_toggleaudit_{chat_id}", icon_custom_emoji_id=CHECK_EMOJI_ID if settings["audit_enabled"] else CROSS_EMOJI_ID)],
        [InlineKeyboardButton(f'{t_sync(lang, "ai_penalty_label")} {penalty_map.get(settings["audit_penalty"], settings["audit_penalty"])}', callback_data=f"ai_setpenalty_{chat_id}", icon_custom_emoji_id=WARN_EMOJI_ID)],
        [InlineKeyboardButton("« " + t_sync(lang, "back_group_manage"), callback_data=f"manage_group_{chat_id}")]
    ])


def get_penalty_keyboard(chat_id: str, lang: str = "zh") -> InlineKeyboardMarkup:
    from lang import t_sync
    pmap = {"delete": t_sync(lang, "ai_delete_only"), "mute_1h": t_sync(lang, "ai_mute_1h"), "kick": t_sync(lang, "ai_kick"), "ban": t_sync(lang, "ai_ban")}
    kb = [[InlineKeyboardButton(pmap.get(k, v), callback_data=f"ai_dopenalty_{chat_id}_{k}", icon_custom_emoji_id=CHECK_EMOJI_ID)] for k, v in PENALTY_OPTIONS.items()]
    kb.append([InlineKeyboardButton("« " + t_sync(lang, "back"), callback_data=f"ai_panel_{chat_id}")])
    return InlineKeyboardMarkup(kb)


async def ai_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data
    print(f"!!! AI_CALLBACK v2: data={data}", flush=True)
    logger.info(f"AI_CALLBACK v2: data={data}")

    try:
        chat_id = int(data.split("_")[2])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception as e:
        logger.error(f"ai callback admin check failed: data={data}, err={e}")
        return

    if data.startswith("ai_buy_"):
        logger.info(f"ai_buy: chat={chat_id}, user={user_id}")
        if await database.check_subscription(chat_id, "ai"):
            logger.info(f"ai_buy: already subscribed, chat={chat_id}")
            await query.answer("该群 AI 审查订阅仍在有效期内。", show_alert=True)
            return
        order_no = f"AI-{chat_id}-{int(time.time())}"
        logger.info(f"ai_buy: creating order {order_no}, currency={config.AI_CURRENCY}, amount={config.AI_PRICE}")
        result = await payment.create_order(order_no, config.AI_CURRENCY, config.AI_PRICE)
        logger.info(f"ai_buy: create_order result ok={result.get('ok')}, error={result.get('error', 'none')}")
        if not result.get("ok"):
            await query.answer(f"创建订单失败：{result.get('error', '未知')}", show_alert=True)
            return
        await query.answer()
        pay_url = result.get("pay_url", "")
        logger.info(f"ai_buy: pay_url={pay_url[:60]}...")
        await database.save_payment_order(order_no, chat_id, user_id, "ai", config.AI_PRICE, config.AI_CURRENCY)
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{payment.EMOJI_DIAMOND}">💎</tg-emoji> <b>AI 审查订阅</b>\n\n'
            f'<tg-emoji emoji-id="{payment.EMOJI_STAR}">🌟</tg-emoji> 金额：{config.AI_PRICE} {config.AI_CURRENCY}\n'
            f"时长：30 天\n\n"
            f"<a href='{pay_url}'>👉 点击此处支付</a>\n\n"
            f"支付后自动激活，10分钟内到账。"
        )
        asyncio.create_task(payment.poll_order(context.bot, chat_id, user_id, order_no, "ai"))
        return

    if data.startswith("ai_panel_"):
        await query.answer()
        settings = await get_ai_settings(chat_id)
        trigger_raw = settings["chat_trigger"] or ""
        triggers = parse_triggers(trigger_raw)
        trigger_display = ", ".join(triggers) if triggers else "未设置"
        sub_active = await database.check_subscription(chat_id, "ai")
        sub_text = f'<tg-emoji emoji-id="5805337324967432449">👑</tg-emoji> 订阅：已激活' if sub_active else '订阅：未订阅'
        text = f'<tg-emoji emoji-id="{ROBOT_EMOJI_ID}">🛡</tg-emoji> <b>AI 助手</b>\n\n{sub_text}（仅审查需要）\nAI聊天: {"✅" if settings["chat_enabled"] else "❌"}（免费）\n触发词: {trigger_display}\n审计: {"✅" if settings["audit_enabled"] else "❌"}（付费）\n审计处罚: {PENALTY_OPTIONS.get(settings["audit_penalty"], settings["audit_penalty"])}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_ai_keyboard(str(chat_id), settings))
        return

    if data.startswith("ai_togglechat_"):
        s = await get_ai_settings(chat_id)
        await update_ai_settings(chat_id, chat_enabled=not s["chat_enabled"])
        await query.answer(f'AI聊天已{"开启" if not s["chat_enabled"] else "关闭"}')
        await query.message.delete()
        s = await get_ai_settings(chat_id)
        triggers = parse_triggers(s["chat_trigger"] or "")
        trigger_display = ", ".join(triggers) if triggers else "未设置"
        text = f'<tg-emoji emoji-id="{ROBOT_EMOJI_ID}">🛡</tg-emoji> <b>AI 助手</b>\n\nAI聊天: {"✅" if s["chat_enabled"] else "❌"}（免费）\n触发词: {trigger_display}\n审计: {"✅" if s["audit_enabled"] else "❌"}（付费）'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_ai_keyboard(str(chat_id), s))
        return

    if data.startswith("ai_toggleaudit_"):
        if config.AI_PRICE != "0" and not await database.check_subscription(chat_id, "ai"):
            await query.answer("⚠️ 需要购买 AI 审查订阅才能开启", show_alert=True)
            return
        s = await get_ai_settings(chat_id)
        await update_ai_settings(chat_id, audit_enabled=not s["audit_enabled"])
        await query.answer(f'AI审计已{"开启" if not s["audit_enabled"] else "关闭"}')
        await query.message.delete()
        s = await get_ai_settings(chat_id)
        triggers = parse_triggers(s["chat_trigger"] or "")
        trigger_display = ", ".join(triggers) if triggers else "未设置"
        text = f'<tg-emoji emoji-id="{ROBOT_EMOJI_ID}">🛡</tg-emoji> <b>AI 助手</b>\n\nAI聊天: {"✅" if s["chat_enabled"] else "❌"}\n审计: {"✅" if s["audit_enabled"] else "❌"}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_ai_keyboard(str(chat_id), s))
        return

    if data.startswith("ai_settrigger_"):
        await query.answer()
        _AWAIT_AI_INPUT[user_id] = {"type": "trigger", "chat_id": chat_id}
        s = await get_ai_settings(chat_id)
        current = s["chat_trigger"] or "未设置"
        current_triggers = parse_triggers(s["chat_trigger"] or "")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"ai_panel_{chat_id}")]])
        await query.message.reply_html(
            f'当前触发词：<code>{current}</code>（共{len(current_triggers)}个）\n\n'
            f'请发送新的触发词，支持<b>多个</b>，用<b>英文逗号</b>隔开\n'
            f'例如：<code>狗, ai, @bot</code>\n'
            f'发送 <code>0</code> 清除全部：',
            reply_markup=kb)
        return

    if data.startswith("ai_setprompt_"):
        await query.answer()
        _AWAIT_AI_INPUT[user_id] = {"type": "prompt", "chat_id": chat_id}
        s = await get_ai_settings(chat_id)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"ai_panel_{chat_id}")]])
        await query.message.reply_html(f'当前提示词：\n<blockquote expandable>{s["chat_prompt"][:200]}</blockquote>\n\n请发送新提示词（不超过300字），发送 0 恢复默认：', reply_markup=kb)
        return

    if data.startswith("ai_setpenalty_"):
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text="选择审计违规处罚方式：", reply_markup=get_penalty_keyboard(str(chat_id)))
        return

    if data.startswith("ai_dopenalty_"):
        penalty = data.split("_")[-1]
        await update_ai_settings(chat_id, audit_penalty=penalty)
        await query.answer(f'审计处罚已设置：{PENALTY_OPTIONS.get(penalty, penalty)}')
        await query.message.delete()
        s = await get_ai_settings(chat_id)
        text = f'<tg-emoji emoji-id="{ROBOT_EMOJI_ID}">🛡</tg-emoji> <b>AI 助手</b>\n\n审计处罚: {PENALTY_OPTIONS.get(s["audit_penalty"], s["audit_penalty"])}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_ai_keyboard(str(chat_id), s))
        return


async def ai_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    await_data = _AWAIT_AI_INPUT.get(user_id)
    if not await_data:
        return
    message = update.message
    if not message or not message.text:
        return
    raw = message.text.strip()
    chat_id = await_data["chat_id"]
    atype = await_data["type"]

    if atype == "trigger":
        _AWAIT_AI_INPUT.pop(user_id, None)
        if raw == "0":
            await update_ai_settings(chat_id, chat_trigger="")
            await message.reply_html(f"{EMOJI_SUCCESS} 触发词已清除")
        else:
            triggers = parse_triggers(raw)
            if not triggers:
                await message.reply_html(f"{EMOJI_WARN} 未识别到有效触发词，请用英文逗号分隔")
                return
            trigger_str = join_triggers(triggers)
            await update_ai_settings(chat_id, chat_trigger=trigger_str[:100])
            await message.reply_html(f"{EMOJI_SUCCESS} 触发词已设置为：<code>{trigger_str[:100]}</code>（共{len(triggers)}个）")
        s = await get_ai_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{ROBOT_EMOJI_ID}">🛡</tg-emoji> <b>AI 助手</b>',
            parse_mode="HTML", reply_markup=get_ai_keyboard(str(chat_id), s))
        return

    if atype == "prompt":
        _AWAIT_AI_INPUT.pop(user_id, None)
        if raw == "0":
            await update_ai_settings(chat_id, chat_prompt=DEFAULT_PROMPT)
            await message.reply_html(f"{EMOJI_SUCCESS} 已恢复默认提示词")
        else:
            if len(raw) > 300:
                await message.reply_html(f"{EMOJI_WARN} 提示词不能超过300字（当前{len(raw)}字）")
                return
            await update_ai_settings(chat_id, chat_prompt=raw)
            await message.reply_html(f"{EMOJI_SUCCESS} 提示词已更新")
        s = await get_ai_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{ROBOT_EMOJI_ID}">🛡</tg-emoji> <b>AI 助手</b>',
            parse_mode="HTML", reply_markup=get_ai_keyboard(str(chat_id), s))
        return


async def _re_async_sub(pattern, replacer, text):
    import re as _re
    result = []
    last = 0
    for m in _re.finditer(pattern, text):
        result.append(text[last:m.start()])
        replacement = await replacer(m)
        result.append(replacement)
        last = m.end()
    result.append(text[last:])
    return "".join(result)


_DICE_MAP = {
    "dice": "🎲", "dart": "🎯", "basketball": "🏀",
    "football": "⚽", "slot": "🎰",
    "🎲": "🎲", "🎯": "🎯", "🏀": "🏀", "⚽": "⚽", "🎰": "🎰",
    # 简写别名
    "dc": "🎯", "dz": "🎲", "basket": "🏀", "foot": "⚽",
}


async def _send_rich_reply(msg, text: str, chat_id: int, context):
    import re as _re
    clean = text
    for m in _re.finditer(r"\{dice(?::([^}]*))?\}", text):
        dtype = _DICE_MAP.get((m.group(1) or "").strip().lower(), "🎲")
        try:
            await context.bot.send_dice(chat_id, emoji=dtype)
        except Exception:
            pass
        clean = clean.replace(m.group(0), "", 1)
    for m in _re.finditer(r"\{([a-z]{2,10})\}", text):
        alias = m.group(1).lower()
        if alias in _DICE_MAP:
            try:
                await context.bot.send_dice(chat_id, emoji=_DICE_MAP[alias])
            except Exception:
                pass
            clean = clean.replace(m.group(0), "", 1)
    # 再发贴纸 {tz:emoji} 或 {tz}
    for m in _re.finditer(r"\{tz(?::([^}]*))?\}", text):
        emoji = (m.group(1) or "").strip()
        file_id = await database.get_sticker_by_emoji(emoji) if emoji else ""
        if not file_id and not emoji:
            file_id = await database.get_random_sticker()
        if file_id:
            try:
                await context.bot.send_sticker(chat_id, sticker=file_id)
            except Exception:
                pass
        clean = clean.replace(m.group(0), "", 1)
    return clean.strip()


# ── 贴纸收集 ──────────────────────────────────────

async def _try_collect_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.channel_post if hasattr(update, 'channel_post') else None)
    if not msg:
        return
    user = update.effective_user
    chat = update.effective_chat
    if not user or user.is_bot:
        return
    if not chat or chat.type != "private":
        return

    collected = []

    # 贴纸
    if msg.sticker:
        emoji = msg.sticker.emoji or "❓"
        await database.add_sticker(msg.sticker.file_id, emoji, user.id)
        collected.append(f"贴纸 {emoji}")

    if collected:
        try:
            sent = await msg.reply_html(
                f'{EMOJI_SUCCESS} 已收藏：{", ".join(collected)}'
            )
            asyncio.create_task(_del_msg(context.bot, chat.id, sent.message_id, 5))
        except Exception:
            pass


async def ai_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # 贴纸收
    if msg:
        await _try_collect_sticker(update, context)
    if not msg or not msg.text:
        return
    chat_id = msg.chat_id
    user = msg.from_user
    if not user or user.is_bot:
        return
    settings = await get_ai_settings(chat_id)

    if settings["audit_enabled"]:
        # 审查功能需要订阅
        if config.AI_PRICE != "0" and not await database.check_subscription(chat_id, "ai"):
            return
        name = user.full_name or user.first_name or str(user.id)
        text = msg.text[:500]
        try:
            audit_prompt = f'请审核以下用户消息是否违规（广告、辱骂、色情、政治敏感等）。\n用户：{name}\n消息：{text}\n\n只回复数字：1（违规）或 0（不违规）。不要回复任何其他内容。'
            result = await ai_chat(audit_prompt, max_tokens=10, temperature=0)
            if not result.get("ok"):
                return
            verdict = result.get("reply", "0").strip()
            if "1" in verdict and "0" not in verdict.replace("1", "", 1):
                penalty = settings["audit_penalty"]
                try:
                    await msg.delete()
                except Exception:
                    pass
                try:
                    if penalty == "mute_1h":
                        until = __import__('datetime').datetime.utcnow() + __import__('datetime').timedelta(hours=1)
                        await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user.id,
                            permissions=ChatPermissions(can_send_messages=False), until_date=until)
                    elif penalty == "kick":
                        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
                        await context.bot.unban_chat_member(chat_id=chat_id, user_id=user.id)
                    elif penalty == "ban":
                        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
                except Exception:
                    pass
                penalty_text = PENALTY_OPTIONS.get(penalty, penalty)
                try:
                    warn_msg = await context.bot.send_message(chat_id=chat_id,
                        text=f'{EMOJI_WARN} {user.mention_html()} AI审计判定违规，已被{penalty_text}。', parse_mode="HTML")
                    asyncio.create_task(_del_msg(context.bot, chat_id, warn_msg.message_id, 10))
                except Exception:
                    pass
            return
        except Exception:
            return

    if not settings["chat_enabled"]:
        return
    trigger_raw = settings["chat_trigger"].strip()
    triggers = parse_triggers(trigger_raw)
    if not triggers:
        return
    matched_trigger, user_prompt = get_triggered_prompt(msg.text.strip(), triggers)
    if matched_trigger is None:
        return
    if not user_prompt:
        user_prompt = "你好"
    try:
        bot_user = await config.get_me(context.bot)
        bot_name = bot_user.first_name
    except Exception:
        bot_name = "AI"
    system_prompt = settings["chat_prompt"].replace("{BOT_NAME}", bot_name)
    user_name = user.full_name or user.first_name or str(user.id)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        
        reply = await _p("ai_chat_reply_text")(chat_id, user.id, user_name, user_prompt)
        if reply:
            if "{tz" not in reply:
                reply = reply.rstrip() + " {tz}"
            clean_text = await _send_rich_reply(msg, reply[:2000], chat_id, context)
            if clean_text:
                await msg.reply_text(clean_text)
        else:
            await msg.reply_html(f"{EMOJI_ERROR} AI 未返回有效回复")
    except Exception as e:
        logger.error(f"AI chat exception: {e}")

# /r command
async def r_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type not in ('group', 'supergroup'):
        await msg.reply_html(f"{EMOJI_WARN} 此命令仅限群组使用。")
        return
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await msg.reply_html(f"{EMOJI_WARN} 只有群主或管理员才能设置 AI 规则。")
            return
    except Exception:
        await msg.reply_html(f"{EMOJI_ERROR} 无法验证权限。")
        return
    rule_text = (msg.text or "").strip()
    rule_text = re.sub(r'^/r\s*', '', rule_text).strip()
    if not rule_text:
        await msg.reply_html(f"{EMOJI_WARN} 用法：<code>/r 规则内容</code>\n例如：<code>/r 禁止讨论政治话题</code>")
        return
        idx = await _p("add_custom_rule")(chat.id, rule_text)
    if idx:
        rules = await _p("get_custom_rules")(chat.id)
        rules_list = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)) if rules else "（无）"
        await msg.reply_html(f'{EMOJI_SUCCESS} AI 规则已添加（共{len(rules)}条）：\n<blockquote expandable>{rules_list}</blockquote>')
    else:
        await msg.reply_html(f"{EMOJI_ERROR} 添加失败。")
    logger.info(f"r_command: chat={chat.id}, user={user.id}, rule={rule_text[:50]}")

# dl command
async def dl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type not in ('group', 'supergroup'):
        await msg.reply_html(f"{EMOJI_WARN} 此命令仅限群组使用。")
        return
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await msg.reply_html(f"{EMOJI_WARN} 只有群主或管理员才能删除 AI 规则。")
            return
    except Exception:
        await msg.reply_html(f"{EMOJI_ERROR} 无法验证权限。")
        return
    arg = (msg.text or "").strip()
    arg = re.sub(r'^/dl\s*', '', arg).strip()
    if not arg.isdigit():
        await msg.reply_html(f"{EMOJI_WARN} 用法：<code>/dl 规则编号</code>\n例如：<code>/dl 1</code>")
        return
    rule_id = int(arg)
    removed = await _p("del_custom_rule")(chat.id, rule_id)
    if removed:
        rules = await _p("get_custom_rules")(chat.id)
        rules_list = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)) if rules else "（无）"
        await msg.reply_html(f'{EMOJI_SUCCESS} 已删除规则：<code>{removed[:50]}</code>\n剩余规则：\n<blockquote expandable>{rules_list}</blockquote>')
    else:
        await msg.reply_html(f"{EMOJI_WARN} 规则 {rule_id} 不存在。")
    logger.info(f"dl_command: chat={chat.id}, user={user.id}, rule_id={rule_id}")


async def _del_msg(bot, chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


FORTUNE_EMOJI_ID = "5447644880824181073"

async def fortune_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return False
    text = msg.text.strip().lower()
    if text not in ("cq", "抽签", "/cq", "/抽签"):
        return False

    chat_id = msg.chat_id
    user = msg.from_user
    user_name = user.full_name or user.first_name or str(user.id)

    logger.info(f"fortune_handler: user={user.id} ({user_name}), text={text}, chat={chat_id}")

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        result = await generate_fortune()
        if not result:
            logger.warning(f"fortune_handler: generate_fortune returned None")
            await msg.reply_html(f"{EMOJI_ERROR} 签筒暂时空了，过会儿再试试～")
            return True

        sign, poem, reading = result
        logger.info(f"fortune_handler: sign={sign}, poem={poem[:30]}..., reading={reading[:30]}...")

        reply = (
            f'{user.mention_html()} 您抽到了签'  f' （{sign}）！\n'
            f'----------------\n'
            f'🎐签诗：{poem}\n'
            f'----------------\n'
            f'🎐解签：{reading}'
        )
        await msg.reply_html(reply)
        logger.info(f"fortune_handler: reply sent for user={user.id}")
        return True

    except Exception as e:
        logger.error(f"fortune_handler error: {e}", exc_info=True)
        await msg.reply_html(f"{EMOJI_ERROR} 抽签出错了：{e}")
        return True
