import io
import random
import asyncio
import logging
from PIL import Image, ImageDraw
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, ChatJoinRequest
from telegram.ext import ContextTypes
import config
from database import get_verify_settings, is_cluster_blacklisted
from welcome import send_welcome_message

logger = logging.getLogger(__name__)

PENDING_VERIFICATIONS = {}  # (chat_id, user_id) → {msg_id, task, correct_ans, ...}
PENDING_JOIN_REQUESTS = {}  # (chat_id, user_id) → {msg_id, task, correct_ans, user_chat_id, ...}

CHECK_EMOJI_ID = "5776375003280838798"
SHIELD_EMOJI_ID = "5931409969613116639"


# ── Math / Captcha generators (shared) ────────────────
def generate_complex_math():
    op = random.choice(["+", "-", "*", "mix"])
    if op == "+":
        a, b = random.randint(12, 89), random.randint(11, 88)
        ans, expr = a + b, f"{a} + {b}"
    elif op == "-":
        a, b = random.randint(30, 99), random.randint(10, 29)
        ans, expr = a - b, f"{a} - {b}"
    elif op == "*":
        a, b = random.randint(3, 12), random.randint(4, 15)
        ans, expr = a * b, f"{a} × {b}"
    else:
        a, b, c = random.randint(2, 9), random.randint(2, 8), random.randint(5, 20)
        ans, expr = a * b + c, f"{a} × {b} + {c}"

    options = {ans}
    while len(options) < 4:
        offset = random.choice([-10, -5, -2, -1, 1, 2, 5, 10, random.randint(-15, 15)])
        fake = ans + offset
        if fake >= 0 and fake != ans:
            options.add(fake)
    return expr, str(ans), [str(x) for x in random.sample(list(options), 4)]


def generate_captcha_image():
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(chars, k=4))
    w, h = 160, 60
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        x1, y1 = random.randint(0, w), random.randint(0, h)
        x2, y2 = random.randint(0, w), random.randint(0, h)
        draw.line([(x1, y1), (x2, y2)], fill=(random.randint(100, 200), random.randint(100, 200), random.randint(100, 200)), width=2)
    for _ in range(120):
        draw.point((random.randint(0, w), random.randint(0, h)), fill=(random.randint(50, 180), random.randint(50, 180), random.randint(50, 180)))
    for i, char in enumerate(code):
        draw.text((18 + i * 32 + random.randint(-3, 3), 15 + random.randint(-4, 4)), char, fill=(random.randint(10, 110), random.randint(10, 110), random.randint(10, 110)))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    options = {code}
    while len(options) < 4:
        options.add("".join(random.choices(chars, k=4)))
    return bio, code, [str(x) for x in random.sample(list(options), 4)]


# ═══════════════════════════════════════════════════════
#  NEW: chat_join_request handler (pre-join verification)
# ═══════════════════════════════════════════════════════
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle ChatJoinRequest — user submits join request (NOT yet in group).
    We send a DM verification BEFORE approving the join request.
    """
    join_req: ChatJoinRequest = update.chat_join_request
    chat = join_req.chat
    user = join_req.user
    user_chat_id = join_req.user_chat_id  # key: allows DM even if user never started bot

    if user.is_bot:
        await join_req.approve()
        return

    shield = f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji>'

    settings = await get_verify_settings(chat.id)
    # 禁止红包挂进入: 集群黑名单用户直接拒绝
    if settings and settings.get("block_blacklist"):
        if await is_cluster_blacklisted(user.id):
            try:
                await join_req.decline()
            except Exception:
                pass
            return
    if not settings or not settings.get("status"):
        # no verification → approve immediately
        try:
            await join_req.approve()
            group_name = chat.title or str(chat.id)
            await context.bot.send_message(
                chat_id=user_chat_id,
                text=f'{shield} 你已加入 <b>{group_name}</b>，欢迎！',
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    # clean up stale pending request for same user+group
    key = (chat.id, user.id)
    old = PENDING_JOIN_REQUESTS.pop(key, None)
    if old:
        old["task"].cancel()
        try:
            await context.bot.delete_message(chat_id=old["user_chat_id"], message_id=old["msg_id"])
        except Exception:
            pass

    mode = settings.get("mode", "button")
    duration = settings.get("duration", 1)

    keyboard = []
    sent_msg = None
    correct_ans = ""
    user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    # ── Build verification DM ──
    if mode == "button":
        text = (
            f'{shield} <b>群组验证 — {chat.title}</b>\n\n'
            f'请在 <b>{duration}</b> 分钟内点击下方按钮完成验证：'
        )
        keyboard = [[InlineKeyboardButton(
            "✅ 点击完成验证",
            callback_data=f"auth_jr_pass_{user.id}_{chat.id}",
            icon_custom_emoji_id=CHECK_EMOJI_ID
        )]]
        correct_ans = "pass"

    elif mode == "math":
        expr, correct_ans, opts = generate_complex_math()
        text = (
            f'{shield} <b>群组验证 — {chat.title}</b>\n\n'
            f'请在 <b>{duration}</b> 分钟内计算算式：\n\n'
            f'<b>{expr} = ?</b>'
        )
        row = []
        for opt in opts:
            row.append(InlineKeyboardButton(
                opt, callback_data=f"auth_jr_{opt}_{user.id}_{chat.id}",
                icon_custom_emoji_id=CHECK_EMOJI_ID
            ))
        keyboard = [row]

    elif mode == "captcha":
        photo_bio, correct_ans, opts = generate_captcha_image()
        text = (
            f'{shield} <b>群组验证 — {chat.title}</b>\n\n'
            f'请在 <b>{duration}</b> 分钟内选择正确的验证码：'
        )
        row = []
        for opt in opts:
            row.append(InlineKeyboardButton(
                opt, callback_data=f"auth_jr_{opt}_{user.id}_{chat.id}",
                icon_custom_emoji_id=CHECK_EMOJI_ID
            ))
        keyboard = [row]

    # ── Send DM ──
    try:
        if mode == "captcha":
            sent_msg = await context.bot.send_photo(
                chat_id=user_chat_id,
                photo=photo_bio,
                caption=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        else:
            sent_msg = await context.bot.send_message(
                chat_id=user_chat_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Failed to send join-request DM to {user.id}: {e}")
        # can't DM → decline silently
        try:
            await join_req.decline()
        except Exception:
            pass
        return

    # ── Schedule timeout ──
    task = asyncio.create_task(_join_request_timeout(
        context, chat.id, user.id, user_chat_id, duration
    ))
    PENDING_JOIN_REQUESTS[key] = {
        "msg_id": sent_msg.message_id,
        "task": task,
        "correct_ans": correct_ans,
        "user_chat_id": user_chat_id,
        "join_request": join_req,
    }


async def _join_request_timeout(context, chat_id, user_id, user_chat_id, duration):
    """Timeout handler: if user doesn't verify, decline the join request."""
    await asyncio.sleep(duration * 60)
    key = (chat_id, user_id)
    data = PENDING_JOIN_REQUESTS.pop(key, None)
    if not data:
        return

    join_req = data.get("join_request")
    # delete DM message
    try:
        await context.bot.delete_message(chat_id=user_chat_id, message_id=data["msg_id"])
    except Exception:
        pass
    # send timeout notice
    try:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=f'<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> 验证超时，入群申请已自动拒绝。'
        )
    except Exception:
        pass
    # decline
    if join_req:
        try:
            await join_req.decline()
        except Exception as e:
            logger.error(f"decline timeout join request failed: {e}")


def _find_active_join_request(chat_id, user_id):
    """Look up the active JoinRequest object from PENDING_JOIN_REQUESTS."""
    key = (chat_id, user_id)
    return PENDING_JOIN_REQUESTS.get(key, {}).get("join_request")


# ═══════════════════════════════════════════════════════
#  Callback handler — handles BOTH pre-join & in-group
# ═══════════════════════════════════════════════════════
async def auth_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat = update.effective_chat
    data = query.data

    shield = f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji>'
    check_ok = f'<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

    # ────────────────────────────────────────────────
    #  A) Pre-join verification callbacks (auth_jr_*)
    #     Format: auth_jr_{answer}_{user_id}_{chat_id}
    # ────────────────────────────────────────────────
    if data.startswith("auth_jr_"):
        parts = data.split("_")
        # parts: ["auth", "jr", answer, user_id, chat_id]
        answer = parts[2]
        target_uid = int(parts[3])
        target_cid = int(parts[4])

        if user.id != target_uid:
            await query.answer("⚠️ 这不是属于你的验证按钮！", show_alert=True)
            return

        key = (target_cid, target_uid)
        vdata = PENDING_JOIN_REQUESTS.pop(key, None)
        if not vdata:
            await query.answer("⚠️ 验证已超时或失效！", show_alert=True)
            return

        vdata["task"].cancel()
        user_chat_id = vdata["user_chat_id"]
        join_req = vdata.get("join_request")

        # delete DM message
        try:
            await context.bot.delete_message(chat_id=user_chat_id, message_id=vdata["msg_id"])
        except Exception:
            pass

        if answer == vdata["correct_ans"]:
            # approve join request
            approved = False
            if join_req:
                try:
                    await join_req.approve()
                    approved = True
                except Exception as e:
                    logger.error(f"approve join_request failed: {e}")

            if approved:
                await query.answer(f"{check_ok} 验证通过！已批准入群。", show_alert=True)
                group_name = "群组"
                try:
                    group_chat = await context.bot.get_chat(target_cid)
                    group_name = group_chat.title or str(target_cid)
                except Exception:
                    pass
                try:
                    await context.bot.send_message(
                        chat_id=user_chat_id,
                        text=f'{check_ok} 验证通过！欢迎加入 <b>{group_name}</b>',
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            else:
                await query.answer("⚠️ 批准失败（可能已超时），请重新申请", show_alert=True)
        else:
            # wrong answer → decline
            if join_req:
                try:
                    await join_req.decline()
                except Exception:
                    pass
            await query.answer("❌ 验证失败！入群申请已拒绝。", show_alert=True)
            try:
                await context.bot.send_message(
                    chat_id=user_chat_id,
                    text='❌ 验证码错误，入群申请已被拒绝。你可以重新申请。'
                )
            except Exception:
                pass
        return

    # ────────────────────────────────────────────────
    #  B) In-group private verification (auth_priv_*)
    #     Legacy: used when join_by_request is on but
    #     user already entered group (admin bypass etc.)
    # ────────────────────────────────────────────────
    if data.startswith("auth_priv_"):
        parts = data.split("_")
        action = parts[2]
        target_uid = int(parts[3])
        target_cid = int(parts[4])

        if user.id != target_uid:
            await query.answer("⚠️ 这不是属于你的验证按钮！", show_alert=True)
            return

        key = (target_cid, target_uid)
        vdata = PENDING_VERIFICATIONS.pop(key, None)
        if not vdata:
            await query.answer("⚠️ 验证已超时或失效！", show_alert=True)
            return

        vdata["task"].cancel()
        from database import delete_verification
        await delete_verification(target_cid, target_uid)

        # delete private DM
        try:
            await context.bot.delete_message(chat_id=user.id, message_id=vdata["msg_id"])
        except Exception:
            pass
        # delete group tip
        if vdata.get("group_tip_id"):
            try:
                await context.bot.delete_message(chat_id=target_cid, message_id=vdata["group_tip_id"])
            except Exception:
                pass

        if action == "pass" and vdata["correct_ans"] == "pass":
            try:
                await context.bot.restrict_chat_member(
                    chat_id=target_cid, user_id=target_uid,
                    permissions=ChatPermissions(
                        can_send_messages=True, can_send_audios=True,
                        can_send_documents=True, can_send_photos=True,
                        can_send_videos=True, can_send_video_notes=True,
                        can_send_voice_notes=True, can_send_polls=True,
                        can_send_other_messages=True, can_add_web_page_previews=True
                    )
                )
                await query.answer("✅ 验证成功！欢迎加入！", show_alert=True)
                group_chat = await context.bot.get_chat(target_cid)
                await send_welcome_message(context, group_chat, user)
                user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
                await context.bot.send_message(
                    chat_id=target_cid,
                    text=f'{check_ok} {user_mention} 私聊验证通过，欢迎加入！',
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"private verify unrestrict fail: {e}")
                await query.answer("⚠️ 放行失败，请联系管理员", show_alert=True)
        else:
            await query.answer("❌ 验证失败！", show_alert=True)
            settings = await get_verify_settings(target_cid)
            penalty = settings.get("penalty", "mute") if settings else "mute"
            try:
                if penalty == "kick":
                    await context.bot.ban_chat_member(chat_id=target_cid, user_id=target_uid)
                    await context.bot.unban_chat_member(chat_id=target_cid, user_id=target_uid)
            except Exception as e:
                logger.error(f"private verify penalty fail: {e}")
        return

    # ────────────────────────────────────────────────
    #  C) In-group verification callbacks (auth_*)
    #     Original flow: user already in group, muted
    # ────────────────────────────────────────────────
    parts = data.split("_")
    action = parts[1]

    if action == "adminpass":
        target_uid = int(parts[2])
        member_stat = await context.bot.get_chat_member(chat.id, user.id)
        if member_stat.status not in ["administrator", "creator"]:
            await query.answer("⚠️ 只有群管理员才能点击此按钮！", show_alert=True)
            return

        key = (chat.id, target_uid)
        if key in PENDING_VERIFICATIONS:
            vdata = PENDING_VERIFICATIONS.pop(key)
            vdata["task"].cancel()
            from database import delete_verification
            await delete_verification(chat.id, target_uid)
            del_chat = vdata.get("private_chat_id", chat.id)
            try:
                await context.bot.delete_message(chat_id=del_chat, message_id=vdata["msg_id"])
            except Exception:
                pass
            if vdata.get("group_tip_id"):
                try:
                    await context.bot.delete_message(chat_id=chat.id, message_id=vdata["group_tip_id"])
                except Exception:
                    pass

        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id, user_id=target_uid,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True,
                    can_send_documents=True, can_send_photos=True,
                    can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True
                )
            )
            await query.answer("✅ 已由管理员手动放行！", show_alert=True)
            target_user = await context.bot.get_chat_member(chat.id, target_uid)
            await send_welcome_message(context, chat, target_user.user)
        except Exception as e:
            logger.error(f"admin pass fail: {e}")
        return

    if action == "pass":
        target_uid = int(parts[2])
        user_answer = "pass"
    else:
        user_answer = parts[2]
        target_uid = int(parts[3])

    if user.id != target_uid:
        await query.answer("⚠️ 这不是属于你的验证按钮！", show_alert=True)
        return

    key = (chat.id, user.id)
    if key not in PENDING_VERIFICATIONS:
        await query.answer("⚠️ 验证已超时或失效！", show_alert=True)
        return

    vdata = PENDING_VERIFICATIONS.pop(key)
    vdata["task"].cancel()
    from database import delete_verification
    await delete_verification(chat.id, user.id)

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=vdata["msg_id"])
    except Exception:
        pass

    if user_answer == vdata["correct_ans"]:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id, user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True,
                    can_send_documents=True, can_send_photos=True,
                    can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True
                )
            )
            await query.answer("✅ 验证成功！欢迎加入！", show_alert=True)
            await send_welcome_message(context, chat, user)
        except Exception as e:
            logger.error(f"unrestrict fail: {e}")
    else:
        await query.answer("❌ 验证失败！只有一次机会，已被处理！", show_alert=True)
        settings = await get_verify_settings(chat.id)
        penalty = settings.get("penalty", "mute") if settings else "mute"
        try:
            if penalty == "kick":
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
                await context.bot.unban_chat_member(chat_id=chat.id, user_id=user.id)
        except Exception as e:
            logger.error(f"penalty fail: {e}")


# ═══════════════════════════════════════════════════════
#  In-group handlers (legacy / groups without join-req)
# ═══════════════════════════════════════════════════════
async def perform_verification(context: ContextTypes.DEFAULT_TYPE, chat, user):
    """In-group verification (user already inside). Used when join_by_request is OFF."""
    if user.is_bot:
        return

    shield = f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji>'

    settings = await get_verify_settings(chat.id)
    if not settings:
        await send_welcome_message(context, chat, user)
        return
    # 禁止红包挂进入: 集群黑名单用户直接踢出
    if settings.get("block_blacklist") and await is_cluster_blacklisted(user.id):
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
        except Exception as e:
            logger.error(f"blacklist ban fail for {user.id} in {chat.id}: {e}")
        return
    if not settings.get("status"):
        await send_welcome_message(context, chat, user)
        return

    key = (chat.id, user.id)
    if key in PENDING_VERIFICATIONS:
        old_data = PENDING_VERIFICATIONS.pop(key, None)
        if old_data:
            old_data["task"].cancel()
            try:
                await context.bot.delete_message(chat_id=chat.id, message_id=old_data["msg_id"])
            except Exception:
                pass
        from database import delete_verification
        await delete_verification(chat.id, user.id)

    # only mute if group does NOT use join_by_request
    if not getattr(chat, "join_by_request", False):
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id, user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=False, can_send_audios=False,
                    can_send_documents=False, can_send_photos=False,
                    can_send_videos=False, can_send_video_notes=False,
                    can_send_voice_notes=False, can_send_polls=False,
                    can_send_other_messages=False, can_add_web_page_previews=False
                )
            )
        except Exception as e:
            logger.error(f"restrict fail for {user.id} in {chat.id}: {e}")
            return

    mode = settings.get("mode", "button")
    duration = settings.get("duration", 1)
    penalty = settings.get("penalty", "mute")

    user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    keyboard = []
    sent_msg = None
    correct_ans = ""

    if mode == "button":
        text = (
            f"{shield} 欢迎 {user_mention}！\n"
            f"请在 <b>{duration}</b> 分钟内点击下方按钮完成验证（只有一次机会）："
        )
        keyboard = [
            [InlineKeyboardButton("点击完成验证", callback_data=f"auth_pass_{user.id}", icon_custom_emoji_id=CHECK_EMOJI_ID)],
            [InlineKeyboardButton("管理员通过", callback_data=f"auth_adminpass_{user.id}")]
        ]
        sent_msg = await context.bot.send_message(
            chat_id=chat.id, text=text,
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )
        correct_ans = "pass"

    elif mode == "math":
        expr, correct_ans, opts = generate_complex_math()
        text = (
            f"{shield} 欢迎 {user_mention}！\n"
            f"请在 <b>{duration}</b> 分钟内计算算式（<b>只有一次机会</b>）：\n\n"
            f"<b>{expr} = ?</b>"
        )
        row = []
        for opt in opts:
            row.append(InlineKeyboardButton(opt, callback_data=f"auth_check_{opt}_{user.id}", icon_custom_emoji_id=CHECK_EMOJI_ID))
        keyboard = [row, [InlineKeyboardButton("管理员通过", callback_data=f"auth_adminpass_{user.id}")]]
        sent_msg = await context.bot.send_message(
            chat_id=chat.id, text=text,
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )

    elif mode == "captcha":
        photo_bio, correct_ans, opts = generate_captcha_image()
        caption = (
            f"{shield} 欢迎 {user_mention}！\n"
            f"请在 <b>{duration}</b> 分钟内选择正确的验证码（<b>只有一次机会</b>）："
        )
        row = []
        for opt in opts:
            row.append(InlineKeyboardButton(opt, callback_data=f"auth_check_{opt}_{user.id}", icon_custom_emoji_id=CHECK_EMOJI_ID))
        keyboard = [row, [InlineKeyboardButton("管理员通过", callback_data=f"auth_adminpass_{user.id}")]]
        sent_msg = await context.bot.send_photo(
            chat_id=chat.id, photo=photo_bio, caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )

    task = asyncio.create_task(_in_group_timeout(context, chat.id, user.id, duration, penalty))
    PENDING_VERIFICATIONS[(chat.id, user.id)] = {
        "msg_id": sent_msg.message_id,
        "task": task,
        "correct_ans": correct_ans
    }
    from database import save_verification
    await save_verification(chat.id, user.id, sent_msg.message_id, correct_ans, duration, penalty)


async def _in_group_timeout(context, chat_id, user_id, duration, penalty):
    await asyncio.sleep(duration * 60)
    key = (chat_id, user_id)
    data = PENDING_VERIFICATIONS.pop(key, None)
    if not data:
        return
    from database import delete_verification
    await delete_verification(chat_id, user_id)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=data["msg_id"])
    except Exception:
        pass
    if penalty == "kick":
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.error(f"timeout kick fail: {e}")


async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group (already inside)."""
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        # If group uses join_by_request, chat_join_request_handler already verified;
        # just send welcome here.
        if getattr(chat, "join_by_request", False):
            await send_welcome_message(context, chat, member)
        else:
            await perform_verification(context, chat, member)


async def chat_member_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if not chat_member:
        return
    old = chat_member.old_chat_member
    new = chat_member.new_chat_member
    user = new.user
    chat = update.effective_chat

    if user.is_bot:
        return

    old_status = old.status
    new_status = new.status

    # 管理员变动 → 更新 chat_admins 表
    from database import add_chat_admin, remove_chat_admin
    try:
        if new_status == "administrator" and old_status != "administrator":
            await add_chat_admin(chat.id, user.id)
        elif old_status == "administrator" and new_status != "administrator":
            await remove_chat_admin(chat.id, user.id)
    except Exception:
        pass

    if old_status in ["left", "banned", "restricted"] and new_status in ["member", "administrator"]:
        logger.info(f"Detected join/unban via chat_member for {user.id} in {chat.id}")
        if getattr(chat, "join_by_request", False):
            await send_welcome_message(context, chat, user)
        else:
            await perform_verification(context, chat, user)
