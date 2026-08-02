import asyncio
import logging
import random
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
from database import add_to_cluster_blacklist

logger = logging.getLogger(__name__)
logger.info("anti_bot module loaded")

WARN_EMOJI = "5447644880824181073"
REDBAG_EMOJI = "5120863672792515559"
COIN_EMOJI = "5258204546391351475"
BILL_EMOJI = "6316504433953868968"
TIP_EMOJI = "5422439311196834318"
TARGET_EMOJI = "5310278924616356636"
LIST_EMOJI = "5258477770735885832"
GOLD_EMOJI = "5440539497383087970"
ALERT_EMOJI = "5220214598585568818"
RED_DOT_EMOJI = "4926956800005112527"
_active_tests = {}


def _generate_question():
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    answer = a + b
    wrongs = set()
    while len(wrongs) < 5:
        w = answer + random.choice([-3, -2, -1, 1, 2, 3, 4, 5])
        if w != answer and w >= 0 and w not in wrongs:
            wrongs.add(w)
    wrongs = list(wrongs)
    options = wrongs + [answer]
    random.shuffle(options)
    return a, b, answer, options


async def check_anti_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not msg.text or not chat:
        return False
    text = msg.text.strip()
    if text != "测挂":
        return False
    if chat.type not in ("group", "supergroup"):
        return False
    user = update.effective_user
    if not user or user.is_bot:
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            return False
    except Exception:
        return False

    # 1. 发送警告
    await context.bot.send_message(
        chat.id,
        f'<tg-emoji emoji-id="{WARN_EMOJI}">⚠️</tg-emoji> <b>反外挂测试即将开始，真人请勿抢</b>',
        parse_mode="HTML"
    )

    # 2. 生成题目 + 金额
    a, b, answer, options = _generate_question()
    total_copies = random.randint(5, 20)
    amount = f"{random.randint(100, 9999)}.{random.randint(10, 99)}"
    remaining = f"{total_copies}/{total_copies}"  # 初始满的

    # 构建答案按钮 (2行×3列)
    buttons = []
    row = []
    for i, opt in enumerate(options):
        row.append(InlineKeyboardButton(str(opt), callback_data=f"atb_answer_{chat.id}_{opt}_{answer}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    reply_markup = InlineKeyboardMarkup(buttons)

    text = (
        f'<tg-emoji emoji-id="{REDBAG_EMOJI}">🧧</tg-emoji> {user.mention_html()} 发送了一个红包\n\n'
        f'<tg-emoji emoji-id="{COIN_EMOJI}">💰</tg-emoji> 总金额：{amount} USDT '
        f'<tg-emoji emoji-id="{BILL_EMOJI}">💴</tg-emoji> 剩余：{remaining}\n\n'
        f'<tg-emoji emoji-id="{TIP_EMOJI}">💡</tg-emoji> 点击下方正确答案领取红包 👇\n'
        f'{a} + {b} = ?'
    )

    sent = await context.bot.send_message(chat.id, text=text, parse_mode="HTML", reply_markup=reply_markup)

    # 记录
    msg_user = update.effective_user
    msg_name = (msg_user.first_name or "") + (" " + msg_user.last_name if msg_user.last_name else "")
    _active_tests[chat.id] = {
        "answer": answer,
        "start_time": time.monotonic(),
        "clicks": {},
        "message_id": sent.message_id,
        "options": options,
        "header_text": text,
        "admin_name": msg_name.strip() or str(msg_user.id),
        "amount": amount,
        "total_copies": total_copies,
    }

    # 30秒后公布结果
    asyncio.create_task(_finish_test(context, chat.id, sent.message_id))
    return True


async def anti_bot_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if not data.startswith("atb_"):
        return

    parts = data.split("_")
    chat_id = int(parts[2])
    chosen = int(parts[3])
    answer = int(parts[4])
    user = query.from_user
    user_id = user.id

    test = _active_tests.get(chat_id)
    if not test:
        await query.answer("测试已结束", show_alert=True)
        return

    # 去重：同一用户多次点击只记录第一次
    if user_id in test["clicks"]:
        _, name, _ = test["clicks"][user_id]
        await query.answer(f"已参与 · {name}", show_alert=True)
        return

    # 记录
    click_time = time.monotonic()
    elapsed = click_time - test["start_time"]
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    name = name.strip() or str(user_id)
    is_correct = chosen == answer
    is_bot = elapsed < 1.0
    test["clicks"][user_id] = (elapsed, name, is_correct)

    # Toast 反馈
    if is_bot:
        flag = "🤖 外挂"
    elif is_correct:
        flag = "✅"
    else:
        flag = "❌"
    await query.answer(f"{flag} {elapsed*1000:.0f}ms", show_alert=True)

    # ── 实时更新消息排名 ──
    clicks = test["clicks"]
    # 按速度排序
    ranked = sorted(clicks.items(), key=lambda x: x[1][0])
    items = []
    for rank, (uid, (e, n, correct)) in enumerate(ranked, 1):
        emoji = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"{rank}"))
        ms = int(e * 1000)
        warn = f" ⚠️{ms}ms" if e < 1.0 else ""
        mark = " ✅" if correct else " ❌"
        items.append(f"{emoji} {n} · {e:.2f}s{mark}{warn}")

    live_text = (
        f'{test["header_text"]}\n\n'
        f'<tg-emoji emoji-id="{TARGET_EMOJI}">🎯</tg-emoji> <b>实时排名</b> ({len(clicks)}人)\n'
        + "\n".join(items) +
        f'\n\n<tg-emoji emoji-id="{TIP_EMOJI}">💡</tg-emoji> 点击答案参与...'
    )

    try:
        await query.edit_message_text(
            live_text, parse_mode="HTML",
            reply_markup=query.message.reply_markup,
            disable_web_page_preview=True
        )
    except Exception:
        pass  # 消息没变化时不报错


async def _finish_test(context, chat_id, msg_id):
    await asyncio.sleep(30)
    test = _active_tests.pop(chat_id, None)
    if not test:
        return

    answer = test["answer"]
    clicks = test["clicks"]  # {uid: (elapsed_sec, name, is_correct)}

    # 分类：正确真人、错误真人、外挂嫌疑
    legit = []    # 正确 + >=1s
    wrong = []     # 错误 + >=1s
    suspects = []  # <1s（无论对错）

    for uid, (elapsed, name, is_correct) in clicks.items():
        entry = (uid, name, elapsed)
        if elapsed < 1.0:
            suspects.append(entry)
        elif is_correct:
            legit.append(entry)
        else:
            wrong.append(entry)

    total = len(clicks)
    amount = test.get("amount", "0.00")
    total_copies = test.get("total_copies", total)
    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")

    remaining_copies = max(0, total_copies - total)
    lines = [
        f'<tg-emoji emoji-id="{TARGET_EMOJI}">🎯</tg-emoji> <b>测挂结果 · {amount} USDT / {total_copies}份</b>',
        f'已领 {total} 份 · 剩余 {remaining_copies} 份',
        '',
        f'<tg-emoji emoji-id="{LIST_EMOJI}">📋</tg-emoji> <b>领取名单</b>',
    ]

    # 真人列表
    for uid, name, elapsed in legit:
        ms = int(elapsed * 1000)
        warn = f' <tg-emoji emoji-id="{WARN_EMOJI}">⚠️</tg-emoji>秒抢 {ms}ms' if elapsed < 2 else ""
        lines.append(f'<tg-emoji emoji-id="{GOLD_EMOJI}">🥇</tg-emoji> {name} · {elapsed:.2f}<tg-emoji emoji-id="{BILL_EMOJI}">💴</tg-emoji> · {now}{warn}')

    if wrong:
        for uid, name, elapsed in wrong:
            lines.append(f'❌ {name} · {elapsed:.2f}s')

    if suspects:
        lines.append('')
        lines.append(f'<tg-emoji emoji-id="{ALERT_EMOJI}">🚨</tg-emoji> <b>外挂嫌疑 ×{len(suspects)}</b>')
        for uid, name, elapsed in suspects:
            ms = int(elapsed * 1000)
            lines.append(f'<tg-emoji emoji-id="{RED_DOT_EMOJI}">🔴</tg-emoji> <b>{name}</b>')
            lines.append(f'    秒抢 {ms}ms')

    result_text = "\n".join(lines)

    # 构建封禁按钮
    kb = []
    if suspects:
        _pending_bans[chat_id] = [(uid, name) for uid, name, _ in suspects]
        _blacklist_candidates[chat_id] = [(uid, name) for uid, name, _ in suspects]
        kb = _build_ban_keyboard(chat_id, _pending_bans[chat_id], _blacklist_candidates[chat_id])

    reply_markup = InlineKeyboardMarkup(kb) if kb else None

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=result_text,
            parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"finish_test edit failed: {e}")


_pending_bans = {}
_blacklist_candidates = {}


def _build_ban_keyboard(chat_id, pending, candidates):
    """构建测挂结果按钮: 封禁按钮 + 加入集群黑名单按钮。

    pending: [(uid, name), ...] 待封禁; candidates: [(uid, name), ...] 黑名单候选。
    """
    kb = []
    if pending:
        kb.append([InlineKeyboardButton(
            f"🚫 一键封禁全部 ({len(pending)}人)",
            callback_data=f"atb_banall_{chat_id}"
        )])
        row = []
        for uid, name in pending:
            row.append(InlineKeyboardButton(
                f"封禁 {name[:6]}", callback_data=f"atb_banone_{chat_id}_{uid}"
            ))
            if len(row) == 3:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
    if candidates:
        kb.append([InlineKeyboardButton(
            f"加入集群黑名单 ({len(candidates)}人)",
            callback_data=f"atb_blacklist_{chat_id}",
            icon_custom_emoji_id="5397994032385239776"
        )])
    return kb


async def anti_bot_ban_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理封禁按钮"""
    query = update.callback_query
    data = query.data
    if not data.startswith("atb_ban"):
        return

    parts = data.split("_")
    chat_id = int(parts[2])
    user_id = query.from_user.id

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能操作", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("atb_banall_"):
        # 只封禁, 保留 _pending_bans/_blacklist_candidates, 让"加入集群黑名单"按钮仍可点
        suspects = _pending_bans.get(chat_id, [])
        banned = 0
        for uid, name in suspects:
            try:
                await context.bot.ban_chat_member(chat_id, uid)
                banned += 1
            except Exception:
                pass
        await query.answer(f"已封禁 {banned}/{len(suspects)} 人", show_alert=True)

    elif data.startswith("atb_banone_"):
        uid = int(parts[3])
        try:
            await context.bot.ban_chat_member(chat_id, uid)
            await query.answer("已封禁", show_alert=True)
            suspects = _pending_bans.get(chat_id, [])
            suspects = [(u, n) for u, n in suspects if u != uid]
            if suspects:
                _pending_bans[chat_id] = suspects
            else:
                _pending_bans.pop(chat_id, None)
        except Exception as e:
            await query.answer(f"封禁失败: {e}", show_alert=True)

    elif data.startswith("atb_blacklist_"):
        candidates = _blacklist_candidates.get(chat_id, [])
        added = 0
        for uid, name in candidates:
            if await add_to_cluster_blacklist(uid, name, reason="anti_bot"):
                added += 1
        _pending_bans.pop(chat_id, None)
        _blacklist_candidates.pop(chat_id, None)
        await query.answer(f"已加入集群黑名单 {added}/{len(candidates)} 人", show_alert=True)

    # 更新按钮
    kb = _build_ban_keyboard(chat_id, _pending_bans.get(chat_id, []), _blacklist_candidates.get(chat_id, []))
    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception:
        pass
