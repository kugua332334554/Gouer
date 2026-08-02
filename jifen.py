import asyncio
import re
from telegram import Update
from telegram.ext import ContextTypes
from database import process_checkin, get_points_settings, add_user_points, get_user_points, get_user_timezone, log_group_action

async def delete_messages_delayed(bot, chat_id: int, message_ids: list, delay: int):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

async def get_group_owner_timezone_offset(context, chat_id: int) -> int:
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        owner = None
        for admin in admins:
            if admin.status == "creator":
                owner = admin.user
                break
        if owner:
            tz_str = await get_user_timezone(owner.id)
        else:
            tz_str = "UTC+8 北京/上海"
    except Exception:
        tz_str = "UTC+8 北京/上海"
    match = re.search(r'UTC([+-]\d+)', tz_str)
    if match:
        return int(match.group(1))
    return 8

async def checkin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.message.text.strip() != "签到":
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    name = update.effective_user.full_name or update.effective_user.first_name
    settings = await get_points_settings(chat_id)
    if not settings or not settings.get("status"):
        return
    tz_offset = await get_group_owner_timezone_offset(context, chat_id)
    result = await process_checkin(chat_id, user_id, tz_offset)
    if result.get("already_checked_in"):
        fail_msg = await update.message.reply_html(
            f'<tg-emoji emoji-id="5767151002666929821">🚫</tg-emoji>{name}，您今天已经签到过啦～'
        )
        # 与签到成功一样, 按 delete_time 设置自动删除(含用户消息和失败提示)
        delete_time = settings.get("delete_time", 0)
        if delete_time > 0:
            asyncio.create_task(delete_messages_delayed(
                context.bot,
                chat_id,
                [update.message.message_id, fail_msg.message_id],
                delete_time
            ))
        return
    gained = result["gained"]
    streak = result["streak"]
    total = result["total"]
    text = (
        f'<tg-emoji emoji-id="5197688912457245639">✅</tg-emoji> {name} 签到成功！\n\n'
        f'获得 {gained} 积分\n'
        f'连续签到 {streak} 天\n'
        f'当前积分: {total}'
    )
    sent_msg = await update.message.reply_html(text)
    await log_group_action(chat_id, user_id, f"checkin_streak_{streak}")
    delete_time = settings.get("delete_time", 0)
    if delete_time > 0:
        asyncio.create_task(delete_messages_delayed(
            context.bot,
            chat_id,
            [update.message.message_id, sent_msg.message_id],
            delete_time
        ))

async def message_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    if update.effective_user.is_bot:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    settings = await get_points_settings(chat_id)
    if not settings or not settings.get("status") or settings.get("msg_points") <= 0:
        return
    if update.message.sticker and settings.get("ignore_stickers"):
        return
    await add_user_points(chat_id, user_id, settings["msg_points"])
    await log_group_action(chat_id, user_id, "message")

async def points_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    points = await get_user_points(chat_id, user_id)
    user_mention = update.effective_user.mention_html()
    await update.message.reply_html(
        f'<tg-emoji emoji-id="5879939498149679716">🔎</tg-emoji>{user_mention}，您的积分是 {points}。'
    )
