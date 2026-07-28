import asyncio
import logging
import datetime
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
import database
from lang import t

logger = logging.getLogger(__name__)
logger.info("night module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
CLOCK_EMOJI_ID = "5776213190387961618"
BELL_EMOJI_ID = "5909201569898827582"
SHIELD_EMOJI_ID = "5931409969613116639"
BACK_EMOJI_ID = "5875082500023258804"
ADD_EMOJI_ID = "5775937998948404844"
MOON_EMOJI_ID = "5814500882506589776"
WARN_EMOJI_ID = "5447644880824181073"
DELETE_EMOJI_ID = "6017288111279575194"

EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'


async def get_night_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, status, start_hour, end_hour, notify FROM group_night WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"chat_id": row[0], "status": bool(row[1]), "start_hour": row[2], "end_hour": row[3], "notify": bool(row[4])}
    except Exception as e:
        logger.error(f"get_night_settings err: {e}", exc_info=True)
    return {"chat_id": chat_id, "status": False, "start_hour": 0, "end_hour": 6, "notify": True}


async def update_night_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_night (chat_id) VALUES (%s)", (chat_id,))
                set_parts = []
                values = []
                for k, v in kwargs.items():
                    set_parts.append(f"{k}=%s")
                    values.append(v)
                values.append(chat_id)
                sql = f"UPDATE group_night SET {', '.join(set_parts)} WHERE chat_id = %s"
                await cur.execute(sql, values)
    except Exception as e:
        logger.error(f"update_night_settings err: {e}", exc_info=True)


async def get_all_active_night() -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, start_hour, end_hour, notify FROM group_night WHERE status = TRUE")
                rows = await cur.fetchall()
                return [{"chat_id": row[0], "start_hour": row[1], "end_hour": row[2], "notify": bool(row[3])} for row in rows]
    except Exception as e:
        logger.error(f"get_all_active_night err: {e}", exc_info=True)
        return []


async def get_group_owner_tz_offset(context, chat_id: int) -> int:
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        owner = next((a.user for a in admins if a.status == "creator"), None)
        if owner:
            from database import get_user_timezone
            tz_str = await get_user_timezone(owner.id)
        else:
            tz_str = "UTC+8 北京/上海"
    except Exception:
        tz_str = "UTC+8 北京/上海"
    match = re.search(r'UTC([+-]\d+)', tz_str)
    return int(match.group(1)) if match else 8


async def get_night_panel_text(settings: dict, tz_offset: int, user_id: int = 0) -> str:
    now_utc = datetime.datetime.utcnow()
    now_local = now_utc + datetime.timedelta(hours=tz_offset)
    status_icon = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if settings["status"] else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    enable_text = await t(user_id, "enable") if user_id else "开启"
    disable_text = await t(user_id, "disable") if user_id else "关闭"
    notify_icon = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> {enable_text}' if settings["notify"] else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji> {disable_text}'
    title = await t(user_id, "night_title") if user_id else "夜间模式"
    desc = await t(user_id, "night_desc") if user_id else "限制群组内用户在指定时间段的发言"
    warning = await t(user_id, "night_warning") if user_id else "提示: 修改时间段或者时区后，请重新开启夜间模式才能生效"
    mode_text = await t(user_id, "night_mode") if user_id else "模式: 全员禁言"
    period_text = await t(user_id, "night_period") if user_id else "时间段"
    notify_text = await t(user_id, "night_notify") if user_id else "开始和结束通知"
    curr_text = await t(user_id, "night_curr_time") if user_id else "当前时间"
    status_text = await t(user_id, "status") if user_id else "状态"
    return (
        f'<tg-emoji emoji-id="{MOON_EMOJI_ID}">🌙</tg-emoji> <b>{title}</b>\n\n'
        f'{desc}\n\n'
        f'{EMOJI_WARN} {warning}\n\n'
        f'{status_text}: {status_icon} {enable_text if settings["status"] else disable_text}\n'
        f'{mode_text} <tg-emoji emoji-id="5260264520080695245">🤫</tg-emoji>\n'
        f'{period_text}: {settings["start_hour"]:02d}:00 到 {settings["end_hour"]:02d}:00\n'
        f'{notify_text}: {notify_icon}\n'
        f'{curr_text}: {now_local.strftime("%Y-%m-%d %H:%M:%S")} UTC{tz_offset:+d}'
    )


def get_night_keyboard(chat_id: str, settings: dict) -> InlineKeyboardMarkup:
    status_btn = InlineKeyboardButton(
        "关闭夜间模式" if settings["status"] else "开启夜间模式",
        callback_data=f"night_toggle_{chat_id}",
        icon_custom_emoji_id=CHECK_EMOJI_ID if not settings["status"] else CROSS_EMOJI_ID
    )
    notify_btn = InlineKeyboardButton(
        "通知:开" if settings["notify"] else "通知:关",
        callback_data=f"night_notify_{chat_id}",
        icon_custom_emoji_id=BELL_EMOJI_ID
    )
    keyboard = [
        [status_btn],
        [
            InlineKeyboardButton("设置开始", callback_data=f"night_starthour_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID),
            InlineKeyboardButton("设置结束", callback_data=f"night_endhour_{chat_id}", icon_custom_emoji_id=CLOCK_EMOJI_ID),
        ],
        [notify_btn],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_hour_keyboard(chat_id: str, hour_type: str) -> InlineKeyboardMarkup:
    keyboard = []
    for row_start in range(0, 24, 4):
        row = []
        for h in range(row_start, min(row_start + 4, 24)):
            row.append(InlineKeyboardButton(
                f"{h:02d}:00", callback_data=f"night_sethour_{chat_id}_{hour_type}_{h}",
                icon_custom_emoji_id=CLOCK_EMOJI_ID
            ))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"group_night_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


async def send_night_panel(context, chat_id: int, target_chat_id: int, user_id: int = 0):
    settings = await get_night_settings(chat_id)
    tz_offset = await get_group_owner_tz_offset(context, chat_id)
    text = await get_night_panel_text(settings, tz_offset, user_id)
    reply_markup = get_night_keyboard(str(chat_id), settings)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def night_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    parts = data.split("_")
    chat_id = parts[-1] if data.startswith("night_sethour_") else parts[2]

    try:
        member = await context.bot.get_chat_member(int(chat_id), user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能管理夜间模式。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("group_night_"):
        await query.answer()
        await query.message.delete()
        await send_night_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("night_toggle_"):
        settings = await get_night_settings(int(chat_id))
        new_status = not settings["status"]
        await update_night_settings(int(chat_id), status=new_status)
        if new_status:
            await apply_night_mode(context, int(chat_id), settings)
        else:
            await remove_night_mode(context, int(chat_id))
        await query.answer(f"{'✅ 已开启' if new_status else '❌ 已关闭'}夜间模式")
        await query.message.delete()
        await send_night_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("night_notify_"):
        settings = await get_night_settings(int(chat_id))
        new_notify = not settings["notify"]
        await update_night_settings(int(chat_id), notify=new_notify)
        await query.answer(f"通知已{'开启' if new_notify else '关闭'}")
        await query.message.delete()
        await send_night_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("night_starthour_"):
        await query.answer()
        await query.message.delete()
        settings = await get_night_settings(int(chat_id))
        tz_offset = await get_group_owner_tz_offset(context, int(chat_id))
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>设置开始时间</b>\n\n当前设置：<b>{settings["start_hour"]:02d}:00</b>\n时区：UTC{tz_offset:+d}（群主时区）\n\n请选择开始时间：',
            parse_mode="HTML",
            reply_markup=get_hour_keyboard(chat_id, "start")
        )
        return

    if data.startswith("night_endhour_"):
        await query.answer()
        await query.message.delete()
        settings = await get_night_settings(int(chat_id))
        tz_offset = await get_group_owner_tz_offset(context, int(chat_id))
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>设置结束时间</b>\n\n当前设置：<b>{settings["end_hour"]:02d}:00</b>\n时区：UTC{tz_offset:+d}（群主时区）\n\n请选择结束时间：',
            parse_mode="HTML",
            reply_markup=get_hour_keyboard(chat_id, "end")
        )
        return

    if data.startswith("night_sethour_"):
        hour_type = parts[3]
        hour = int(parts[4])
        if hour_type == "start":
            await update_night_settings(int(chat_id), start_hour=hour)
        else:
            await update_night_settings(int(chat_id), end_hour=hour)
        settings = await get_night_settings(int(chat_id))
        if settings["status"]:
            await query.answer(f"已设置，⚠️请重新开启夜间模式生效", show_alert=True)
        else:
            await query.answer(f"✅ 已设置{ '开始' if hour_type == 'start' else '结束'}时间为 {hour:02d}:00")
        await query.message.delete()
        await send_night_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return


async def apply_night_mode(context, chat_id: int, settings: dict):
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        admin_ids = {a.user.id for a in admins}
        tz_offset = await get_group_owner_tz_offset(context, chat_id)
        now_utc = datetime.datetime.utcnow()
        now_local = now_utc + datetime.timedelta(hours=tz_offset)
        current_hour = now_local.hour
        start_h = settings["start_hour"]
        end_h = settings["end_hour"]
        if start_h < end_h:
            in_night = start_h <= current_hour < end_h
        else:
            in_night = current_hour >= start_h or current_hour < end_h
        if in_night:
            for admin in admins:
                if admin.user.is_bot or admin.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                    continue
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id, user_id=admin.user.id,
                        permissions=ChatPermissions(can_send_messages=False)
                    )
                except Exception:
                    pass
            if settings.get("notify", True):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f'<tg-emoji emoji-id="{MOON_EMOJI_ID}">🌙</tg-emoji> <b>夜间模式已开启</b>\n\n'
                             f'全员禁言中 ({start_h:02d}:00 - {end_h:02d}:00)\n'
                             f'管理员不受影响。',
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"apply_night_mode err: {e}", exc_info=True)


async def remove_night_mode(context, chat_id: int):
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.user.is_bot or admin.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                continue
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat_id, user_id=admin.user.id,
                    permissions=ChatPermissions(
                        can_send_messages=True, can_send_audios=True, can_send_documents=True,
                        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                        can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"remove_night_mode err: {e}", exc_info=True)


async def night_scheduler(context: ContextTypes.DEFAULT_TYPE):
    try:
        active_list = await get_all_active_night()
        for item in active_list:
            try:
                chat_id = item["chat_id"]
                tz_offset = await get_group_owner_tz_offset(context, chat_id)
                now_utc = datetime.datetime.utcnow()
                now_local = now_utc + datetime.timedelta(hours=tz_offset)
                current_hour = now_local.hour
                current_minute = now_local.minute
                start_h = item["start_hour"]
                end_h = item["end_hour"]
                if start_h < end_h:
                    in_night = start_h <= current_hour < end_h
                else:
                    in_night = current_hour >= start_h or current_hour < end_h
                is_start_minute = (current_hour == start_h and current_minute == 0)
                is_end_minute = (current_hour == end_h and current_minute == 0)

                if in_night:
                    admins = await context.bot.get_chat_administrators(chat_id)
                    for admin in admins:
                        if admin.user.is_bot or admin.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                            continue
                        try:
                            await context.bot.restrict_chat_member(
                                chat_id=chat_id, user_id=admin.user.id,
                                permissions=ChatPermissions(can_send_messages=False)
                            )
                        except Exception:
                            pass
                    if is_start_minute and item.get("notify", True):
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=f'<tg-emoji emoji-id="{MOON_EMOJI_ID}">🌙</tg-emoji> <b>夜间模式已开始</b>\n\n'
                                     f'全员禁言中 ({start_h:02d}:00 - {end_h:02d}:00)\n管理员不受影响。',
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                elif is_end_minute and item.get("notify", True):
                    admins = await context.bot.get_chat_administrators(chat_id)
                    for admin in admins:
                        if admin.user.is_bot or admin.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                            continue
                        try:
                            await context.bot.restrict_chat_member(
                                chat_id=chat_id, user_id=admin.user.id,
                                permissions=ChatPermissions(
                                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                                    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                                    can_add_web_page_previews=True
                                )
                            )
                        except Exception:
                            pass
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> <b>夜间模式已结束</b>\n\n全员禁言已解除。',
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"night_scheduler item err chat={item.get('chat_id')}: {e}")
    except Exception as e:
        logger.error(f"night_scheduler err: {e}", exc_info=True)


async def run_night_scheduler(application):
    await asyncio.sleep(15)
    while True:
        try:
            await night_scheduler(application)
        except Exception as e:
            logger.error(f"run_night_scheduler err: {e}", exc_info=True)
        await asyncio.sleep(60)
