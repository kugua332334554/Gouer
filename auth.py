import io
import random
import asyncio
import logging
from PIL import Image, ImageDraw
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import config
from database import get_verify_settings

logger = logging.getLogger(__name__)

PENDING_VERIFICATIONS = {}

CHECK_EMOJI_ID = "5776375003280838798"

def generate_complex_math():
    op = random.choice(["+", "-", "*", "mix"])
    if op == "+":
        a, b = random.randint(12, 89), random.randint(11, 88)
        ans = a + b
        expr = f"{a} + {b}"
    elif op == "-":
        a, b = random.randint(30, 99), random.randint(10, 29)
        ans = a - b
        expr = f"{a} - {b}"
    elif op == "*":
        a, b = random.randint(3, 12), random.randint(4, 15)
        ans = a * b
        expr = f"{a} × {b}"
    else:
        a, b, c = random.randint(2, 9), random.randint(2, 8), random.randint(5, 20)
        ans = a * b + c
        expr = f"{a} × {b} + {c}"
        
    options = {ans}
    while len(options) < 4:
        offset = random.choice([-10, -5, -2, -1, 1, 2, 5, 10, random.randint(-15, 15)])
        fake = ans + offset
        if fake >= 0 and fake != ans:
            options.add(fake)
            
    opts_list = list(options)
    random.shuffle(opts_list)
    return expr, str(ans), [str(x) for x in opts_list]

def generate_captcha_image():
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(chars, k=4))
    
    width, height = 160, 60
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    for _ in range(6):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        color = (random.randint(100, 200), random.randint(100, 200), random.randint(100, 200))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=2)
        
    for _ in range(120):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=(random.randint(50, 180), random.randint(50, 180), random.randint(50, 180)))
        
    for i, char in enumerate(code):
        char_color = (random.randint(10, 110), random.randint(10, 110), random.randint(10, 110))
        x = 18 + i * 32 + random.randint(-3, 3)
        y = 15 + random.randint(-4, 4)
        draw.text((x, y), char, fill=char_color)
        
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    
    options = {code}
    while len(options) < 4:
        options.add("".join(random.choices(chars, k=4)))

    opts_list = list(options)
    random.shuffle(opts_list)
    
    return bio, code, opts_list

async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    shield_emoji = getattr(config, "EMOJI_SHIELD", '<tg-emoji emoji-id="5931409969613116639">🛡</tg-emoji>')
    
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
            
        settings = await get_verify_settings(chat.id)
        if not settings or not settings.get("status"):
            continue
            
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=member.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_audios=False,
                    can_send_documents=False,
                    can_send_photos=False,
                    can_send_videos=False,
                    can_send_video_notes=False,
                    can_send_voice_notes=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                )
            )
        except Exception as e:
            logger.error(f"restrict fail: {e}")
            continue

        mode = settings.get("mode", "button")
        duration = settings.get("duration", 1)
        penalty = settings.get("penalty", "mute")
        
        user_mention = f'<a href="tg://user?id={member.id}">{member.first_name}</a>'
        keyboard = []
        sent_msg = None
        correct_ans = ""
        
        if mode == "button":
            text = (
                f"{shield_emoji} 欢迎 {user_mention}！\n"
                f"请在 <b>{duration}</b> 分钟内点击下方按钮完成验证（只有一次机会）："
            )
            keyboard = [
                [InlineKeyboardButton("点击完成验证", callback_data=f"auth_pass_{member.id}", style="primary", icon_custom_emoji_id=CHECK_EMOJI_ID)],
                [InlineKeyboardButton("管理员通过", callback_data=f"auth_adminpass_{member.id}")]
            ]
            sent_msg = await context.bot.send_message(
                chat_id=chat.id, 
                text=text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="HTML"
            )
            correct_ans = "pass"
            
        elif mode == "math":
            expr, correct_ans, opts = generate_complex_math()
            text = (
                f"{shield_emoji} 欢迎 {user_mention}！\n"
                f"请在 <b>{duration}</b> 分钟内计算算式（<b>只有一次机会</b>）：\n\n"
                f"<b>{expr} = ?</b>"
            )
            row = []
            for opt in opts:
                cb_data = f"auth_check_{opt}_{member.id}"
                row.append(InlineKeyboardButton(opt, callback_data=cb_data, icon_custom_emoji_id=CHECK_EMOJI_ID))
            
            keyboard = [row, [InlineKeyboardButton("管理员通过", callback_data=f"auth_adminpass_{member.id}")]]
            
            sent_msg = await context.bot.send_message(
                chat_id=chat.id, 
                text=text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="HTML"
            )
            
        elif mode == "captcha":
            photo_bio, correct_ans, opts = generate_captcha_image()
            caption = (
                f"{shield_emoji} 欢迎 {user_mention}！\n"
                f"请在 <b>{duration}</b> 分钟内选择正确的验证码（<b>只有一次机会</b>）："
            )
            row = []
            for opt in opts:
                cb_data = f"auth_check_{opt}_{member.id}"
                row.append(InlineKeyboardButton(opt, callback_data=cb_data, icon_custom_emoji_id=CHECK_EMOJI_ID))
            
            keyboard = [row, [InlineKeyboardButton("管理员通过", callback_data=f"auth_adminpass_{member.id}")]]
            
            sent_msg = await context.bot.send_photo(
                chat_id=chat.id,
                photo=photo_bio,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )

        task = asyncio.create_task(handle_timeout(context, chat.id, member.id, duration, penalty))
        PENDING_VERIFICATIONS[(chat.id, member.id)] = {
            "msg_id": sent_msg.message_id,
            "task": task,
            "correct_ans": correct_ans
        }

async def handle_timeout(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, duration: int, penalty: str):
    await asyncio.sleep(duration * 60)
    key = (chat_id, user_id)
    if key in PENDING_VERIFICATIONS:
        data = PENDING_VERIFICATIONS.pop(key)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=data["msg_id"])
        except Exception:
            pass
            
        try:
            if penalty == "kick":
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.error(f"timeout penalty fail: {e}")

async def auth_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat = update.effective_chat
    data = query.data
    
    parts = data.split("_")
    action = parts[1]
    
    if action == "adminpass":
        target_user_id = int(parts[2])
        member_stat = await context.bot.get_chat_member(chat.id, user.id)
        if member_stat.status not in ["administrator", "creator"]:
            await query.answer("⚠️ 只有群管理员才能点击此按钮！", show_alert=True)
            return
            
        key = (chat.id, target_user_id)
        if key in PENDING_VERIFICATIONS:
            v_info = PENDING_VERIFICATIONS.pop(key)
            v_info["task"].cancel()
            try:
                await context.bot.delete_message(chat_id=chat.id, message_id=v_info["msg_id"])
            except Exception:
                pass

        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await query.answer("✅ 已由管理员手动放行！", show_alert=True)
        except Exception as e:
            logger.error(f"admin pass fail: {e}")
        return

    if action == "pass":
        target_user_id = int(parts[2])
        user_answer = "pass"
    else:
        user_answer = parts[2]
        target_user_id = int(parts[3])

    if user.id != target_user_id:
        await query.answer("⚠️ 这不是属于你的验证按钮！", show_alert=True)
        return

    key = (chat.id, user.id)
    if key not in PENDING_VERIFICATIONS:
        await query.answer("⚠️ 验证已超时或失效！", show_alert=True)
        return

    v_info = PENDING_VERIFICATIONS.pop(key)
    v_info["task"].cancel()
    
    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=v_info["msg_id"])
    except Exception:
        pass

    if user_answer == v_info["correct_ans"]:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await query.answer("✅ 验证成功！欢迎加入！", show_alert=True)
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
            logger.error(f"wrong answer penalty fail: {e}")
