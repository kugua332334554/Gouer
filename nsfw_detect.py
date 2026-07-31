# NSFW detection — uses helloxz/nsfw Docker API, extracts video frame 1
import os
import io
import subprocess
import tempfile
import logging
import httpx
import database
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

NSFW_API_URL = os.getenv("NSFW_API_URL", "http://127.0.0.1:6086")
NSFW_TOKEN = os.getenv("NSFW_TOKEN", "")
NSFW_ENABLED = os.getenv("NSFW_ENABLED", "1") == "1"  # global toggle

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
SHIELD_EMOJI_ID = "5931409969613116639"
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_NSFW = '<tg-emoji emoji-id="5933629020301169337">🔞</tg-emoji>'


# ── Settings ──────────────────────────────────────────
async def get_nsfw_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT enabled, penalty, threshold_val FROM group_nsfw WHERE chat_id=%s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"enabled": bool(row[0]), "penalty": row[1], "threshold": float(row[2])}
    except Exception:
        pass
    return {"enabled": False, "penalty": "delete", "threshold": 0.8}


async def update_nsfw_settings(chat_id: int, **kwargs):
    if not kwargs: return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_nsfw (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{database.validate_column_name(k)}=%s"); vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_nsfw SET {', '.join(parts)} WHERE chat_id=%s", vals)
    except Exception as e:
        logger.error(f"update_nsfw_settings err: {e}")


# ── Admin keyboard ────────────────────────────────────
def get_nsfw_keyboard(chat_id: str, s: dict) -> InlineKeyboardMarkup:
    status = "✅ 开启" if s["enabled"] else "❌ 关闭"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"状态: {status}", callback_data=f"nsfw_toggle_{chat_id}",
                              icon_custom_emoji_id=CHECK_EMOJI_ID if s["enabled"] else CROSS_EMOJI_ID)],
        [InlineKeyboardButton(f"惩罚: {s['penalty']}", callback_data=f"nsfw_pen_{chat_id}",
                              icon_custom_emoji_id=SHIELD_EMOJI_ID)],
        [InlineKeyboardButton(f"阈值: {s['threshold']}", callback_data=f"nsfw_thr_{chat_id}",
                              icon_custom_emoji_id=SHIELD_EMOJI_ID)],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]
    ])


# ── Callback handler ──────────────────────────────────
async def nsfw_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user; user_id = user.id
    data = query.data; parts = data.split("_")
    chat_id = int(parts[2])

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True); return
    except Exception: return

    if data.startswith("nsfw_panel_"):
        await query.answer()
        s = await get_nsfw_settings(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>NSFW 色情识别</b>\n\n'
                 f'检测群内图片/视频/GIF/圆形视频，自动识别色情内容并处理。\n\n'
                 f'状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}\n'
                 f'惩罚: {s["penalty"]}\n阈值: {s["threshold"]}',
            parse_mode="HTML", reply_markup=get_nsfw_keyboard(str(chat_id), s))
        return

    if data.startswith("nsfw_toggle_"):
        s = await get_nsfw_settings(chat_id)
        await update_nsfw_settings(chat_id, enabled=not s["enabled"])
        await query.answer(f'已{"开启" if not s["enabled"] else "关闭"}')
        s = await get_nsfw_settings(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>NSFW 色情识别</b>\n\n'
                 f'状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}\n'
                 f'惩罚: {s["penalty"]}\n阈值: {s["threshold"]}',
            parse_mode="HTML", reply_markup=get_nsfw_keyboard(str(chat_id), s))
        return

    # pen cycle: delete → mute → kick → ban
    if data.startswith("nsfw_pen_"):
        s = await get_nsfw_settings(chat_id)
        cycle = ["delete", "mute", "kick", "ban"]
        cur = s["penalty"]
        new_pen = cycle[(cycle.index(cur) + 1) % len(cycle)] if cur in cycle else "delete"
        await update_nsfw_settings(chat_id, penalty=new_pen)
        await query.answer(f'惩罚: {new_pen}')
        s = await get_nsfw_settings(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>NSFW 色情识别</b>\n\n'
                 f'状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}\n'
                 f'惩罚: {new_pen}\n阈值: {s["threshold"]}',
            parse_mode="HTML", reply_markup=get_nsfw_keyboard(str(chat_id), s))
        return

    # threshold cycle: 0.6 → 0.7 → 0.8 → 0.9
    if data.startswith("nsfw_thr_"):
        s = await get_nsfw_settings(chat_id)
        cycle = [0.6, 0.7, 0.8, 0.9]
        cur = s.get("threshold", 0.8)
        new_thr = cycle[((cycle.index(cur) if cur in cycle else 2) + 1) % len(cycle)]
        await update_nsfw_settings(chat_id, threshold_val=new_thr)
        await query.answer(f'阈值: {new_thr}')
        s = await get_nsfw_settings(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>NSFW 色情识别</b>\n\n'
                 f'状态: {"✅ 开启" if s["enabled"] else "❌ 关闭"}\n'
                 f'惩罚: {s["penalty"]}\n阈值: {new_thr}',
            parse_mode="HTML", reply_markup=get_nsfw_keyboard(str(chat_id), s))
        return


# ── Frame scanning ───────────────────────────────────
MAX_VIDEO_DURATION = 50  # only scan videos < 50s

def _scan_video_frames(file_bytes: bytes, threshold: float = 0.6) -> float:
    """Scan video frames every 0.5s. Returns highest NSFW score found (>0.6=blocked)."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
            tmp_in.write(file_bytes)
            tmp_in_path = tmp_in.name

        # get duration via ffprobe
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", tmp_in_path
        ], capture_output=True, text=True, timeout=10)
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0

        if duration <= 0 or duration >= MAX_VIDEO_DURATION:
            os.unlink(tmp_in_path)
            return 0.0  # skip: too short or too long

        # scan frames every 0.5s
        max_score = 0.0
        t = 0.0
        while t <= duration:
            result = subprocess.run([
                "ffmpeg", "-y", "-ss", str(t), "-i", tmp_in_path,
                "-vframes", "1", "-f", "image2", "-"
            ], capture_output=True, timeout=10)
            frame_bytes = result.stdout
            if frame_bytes and len(frame_bytes) > 100:
                with httpx.Client(timeout=15) as client:
                    check = client.post(
                        f"{NSFW_API_URL}/api/upload_check",
                        files={"file": ("frame.jpg", io.BytesIO(frame_bytes), "image/jpeg")})
                try:
                    d = check.json()
                    if d.get("code") == 200:
                        score = d["data"].get("nsfw", 0)
                        if score > max_score:
                            max_score = score
                        if score >= threshold:
                            break  # hit threshold, stop scanning
                except Exception:
                    pass
            t += 0.5

        os.unlink(tmp_in_path)
        return max_score
    except Exception as e:
        logger.error(f"scan_video_frames failed: {e}")
        return 0.0


# ── NSFW check ────────────────────────────────────────
async def _check_nsfw(file_bytes: bytes) -> dict:
    """Call NSFW API. Returns {"is_nsfw": bool, "nsfw": float, "sfw": float}."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {}
            if NSFW_TOKEN:
                headers["Authorization"] = f"Bearer {NSFW_TOKEN}"
            resp = await client.post(
                f"{NSFW_API_URL}/api/upload_check",
                files={"file": ("frame.jpg", io.BytesIO(file_bytes), "image/jpeg")},
                headers=headers)
            data = resp.json()
            if data.get("code") == 200:
                d = data["data"]
                return {"is_nsfw": d.get("is_nsfw", False), "nsfw": d.get("nsfw", 0.0), "sfw": d.get("sfw", 0.0)}
            return {"is_nsfw": False, "nsfw": 0.0, "sfw": 1.0}
    except Exception as e:
        logger.error(f"NSFW API call failed: {e}")
        return {"is_nsfw": False, "nsfw": 0.0, "sfw": 1.0}


# ── Message handler ───────────────────────────────────
VIDEO_TYPES = {"video", "animation", "video_note"}

async def nsfw_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check incoming media for NSFW content."""
    if not NSFW_ENABLED:
        return False

    msg = update.message or update.channel_post
    if not msg:
        return False

    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False

    # get settings
    s = await get_nsfw_settings(chat.id)
    if not s["enabled"]:
        return False

    # determine media to check
    file_id = None
    is_video = False
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.video:
        file_id = msg.video.file_id; is_video = True
    elif msg.animation:
        file_id = msg.animation.file_id; is_video = True
    elif msg.video_note:
        file_id = msg.video_note.file_id; is_video = True
    elif msg.sticker and not msg.sticker.is_animated:
        file_id = msg.sticker.file_id
    elif msg.document:
        mime = msg.document.mime_type or ""
        if any(t in mime for t in ("image", "video", "gif")):
            file_id = msg.document.file_id
            is_video = "video" in mime

    if not file_id:
        return False

    try:
        # download file
        tg_file = await context.bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_bytes = bytes(file_bytes)

        # skip large files (>10MB)
        if len(file_bytes) > 10 * 1024 * 1024:
            return False

        # check NSFW: scan frames for video, single check for image
        import asyncio as _asyncio
        if is_video and len(file_bytes) < 10 * 1024 * 1024:
            # scan frames every 0.5s in a thread to avoid blocking
            loop = _asyncio.get_event_loop()
            nsfw_score = await loop.run_in_executor(None, _scan_video_frames, file_bytes, threshold)
        else:
            result = await _check_nsfw(file_bytes)
            nsfw_score = result["nsfw"]

        # use DB threshold, default 0.8
        threshold = s.get("threshold", 0.8)

        if nsfw_score >= threshold:
            user = update.effective_user
            user_id = user.id if user else 0
            penalty = s["penalty"]

            # delete the message
            try:
                await context.bot.delete_message(chat_id=chat.id, message_id=msg.message_id)
            except Exception:
                pass

            # apply penalty
            penalty_text = ""
            try:
                from telegram import ChatPermissions
                from datetime import datetime, timedelta
                if penalty == "mute":
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id, user_id=user_id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=datetime.utcnow() + timedelta(seconds=3600))
                    penalty_text = "已禁言 1 小时"
                elif penalty == "kick":
                    await context.bot.ban_chat_member(chat.id, user_id)
                    await context.bot.unban_chat_member(chat.id, user_id)
                    penalty_text = "已踢出"
                elif penalty == "ban":
                    await context.bot.ban_chat_member(chat.id, user_id)
                    penalty_text = "已封禁"
                else:
                    penalty_text = "消息已删除"
            except Exception as e:
                logger.error(f"NSFW penalty failed: {e}")
                penalty_text = "消息已删除"

            # send warning with auto-delete
            warn_msg = await context.bot.send_message(
                chat_id=chat.id,
                text=f'{EMOJI_NSFW} 检测到色情内容（{nsfw_score:.0%}），{penalty_text}',
                parse_mode="HTML")
            # auto-delete warning after 10s
            import asyncio
            async def _del():
                await asyncio.sleep(10)
                try: await context.bot.delete_message(chat_id=chat.id, message_id=warn_msg.message_id)
                except: pass
            asyncio.create_task(_del())

            return True
    except Exception as e:
        logger.error(f"nsfw_check_handler err: {e}")

    return False
