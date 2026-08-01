import asyncio
import logging
import datetime
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database
from database import validate_column_name
from lang import t_sync, DEFAULT_LANG

logger = logging.getLogger(__name__)

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
CLOCK_EMOJI_ID = "5258419835922030550"
ADD_EMOJI_ID = "5775937998948404844"
BACK_EMOJI_ID = "5875082500023258804"
EDIT_EMOJI_ID = "5884510167986343350"
DELETE_EMOJI_ID = "6017288111279575194"
MEDIA_EMOJI_ID = "5395440575543520059"
BTN_EMOJI_ID = "5879841310902324730"
TEXT_EMOJI_ID = "5879895758202735862"
PREVIEW_EMOJI_ID = "5960714428394507968"
WARN_EMOJI_ID = "5447644880824181073"
STAR_EMOJI_ID = "6323440286445867472"
CAMERA_EMOJI_ID = "5771695636411847302"
LINK_EMOJI_ID = "5879585266426973039"
FROG_EMOJI_ID = "5355051922862653659"
SKIP_EMOJI_ID = "5875506366050734240"

EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

import html as html_mod

from welcome import get_message_html, preprocess_button_text, parse_welcome_buttons
from lang import t

_AWAIT_DINGSHI_INPUT = {}


def _extract_group_chat_id(data: str) -> int:
    parts = data.split("_")
    if data.startswith("dingshi_edit_") or data.startswith("dingshi_skip_") or data.startswith("dingshi_clear_"):
        return int(parts[3])
    return int(parts[2])


def _extract_dingshi_id(data: str) -> int:
    parts = data.split("_")
    return int(parts[-1])


def get_step_keyboard(chat_id: str, dingshi_id: int, step: str, show_clear: bool = False, show_skip: bool = True) -> InlineKeyboardMarkup:
    buttons = []
    if show_skip:
        buttons.append(InlineKeyboardButton("跳过此步", callback_data=f"dingshi_skip_{step}_{chat_id}_{dingshi_id}", icon_custom_emoji_id=SKIP_EMOJI_ID))
    if show_clear:
        buttons.append(InlineKeyboardButton("清空", callback_data=f"dingshi_clear_{step}_{chat_id}_{dingshi_id}", icon_custom_emoji_id=DELETE_EMOJI_ID))
    if dingshi_id:
        cb = f"dingshi_detail_{chat_id}_{dingshi_id}"
    else:
        cb = f"group_dingshi_{chat_id}"
    buttons.append(InlineKeyboardButton("取消", callback_data=cb))
    return InlineKeyboardMarkup([buttons])


async def get_dingshi_count(chat_id: int) -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM group_dingshi WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


async def get_dingshi_list(chat_id: int) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, schedule_time, schedule_days, interval_minutes, content_text, buttons_text, media_type, media_file_id, status, last_sent_date, last_sent_at, created_at FROM group_dingshi WHERE chat_id = %s ORDER BY id ASC",
                    (chat_id,))
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "id": row[0], "chat_id": row[1], "schedule_time": row[2], "schedule_days": row[3] or "*",
                        "interval_minutes": row[4] or 0,
                        "content_text": row[5], "buttons_text": row[6], "media_type": row[7], "media_file_id": row[8],
                        "status": bool(row[9]), "last_sent_date": row[10], "last_sent_at": row[11], "created_at": row[12]
                    })
                return result
    except Exception as e:
        logger.error(f"get_dingshi_list err: {e}", exc_info=True)
        return []


async def get_dingshi_by_id(dingshi_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, schedule_time, schedule_days, interval_minutes, content_text, buttons_text, media_type, media_file_id, status, last_sent_date, last_sent_at, created_at FROM group_dingshi WHERE id = %s",
                    (dingshi_id,))
                row = await cur.fetchone()
                if row:
                    return {
                        "id": row[0], "chat_id": row[1], "schedule_time": row[2], "schedule_days": row[3] or "*",
                        "interval_minutes": row[4] or 0,
                        "content_text": row[5], "buttons_text": row[6], "media_type": row[7], "media_file_id": row[8],
                        "status": bool(row[9]), "last_sent_date": row[10], "last_sent_at": row[11], "created_at": row[12]
                    }
    except Exception as e:
        logger.error(f"get_dingshi_by_id err: {e}", exc_info=True)
    return None


async def create_dingshi(chat_id: int, schedule_time: str, schedule_days: str = "*", interval_minutes: int = 0) -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO group_dingshi (chat_id, schedule_time, schedule_days, interval_minutes) VALUES (%s, %s, %s, %s)",
                    (chat_id, schedule_time, schedule_days, interval_minutes))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"create_dingshi err: {e}", exc_info=True)
        return 0


async def update_dingshi(dingshi_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                set_parts = []
                values = []
                for k, v in kwargs.items():
                    set_parts.append(f"{validate_column_name(k)}=%s")
                    values.append(v)
                values.append(dingshi_id)
                sql = f"UPDATE group_dingshi SET {', '.join(set_parts)} WHERE id = %s"
                await cur.execute(sql, values)
    except Exception as e:
        logger.error(f"update_dingshi err: {e}", exc_info=True)


async def delete_dingshi(dingshi_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM group_dingshi WHERE id = %s", (dingshi_id,))
    except Exception as e:
        logger.error(f"delete_dingshi err: {e}", exc_info=True)


async def toggle_dingshi_status(dingshi_id: int) -> bool:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM group_dingshi WHERE id = %s", (dingshi_id,))
                row = await cur.fetchone()
                if row:
                    new_status = not bool(row[0])
                    await cur.execute("UPDATE group_dingshi SET status = %s WHERE id = %s", (new_status, dingshi_id))
                    return new_status
    except Exception as e:
        logger.error(f"toggle_dingshi_status err: {e}", exc_info=True)
    return False


async def get_all_active_dingshi() -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, schedule_time, schedule_days, interval_minutes, content_text, buttons_text, media_type, media_file_id, status, last_sent_date, last_sent_at, created_at FROM group_dingshi WHERE status = TRUE")
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "id": row[0], "chat_id": row[1], "schedule_time": row[2], "schedule_days": row[3] or "*",
                        "interval_minutes": row[4] or 0,
                        "content_text": row[5], "buttons_text": row[6], "media_type": row[7], "media_file_id": row[8],
                        "status": bool(row[9]), "last_sent_date": row[10], "last_sent_at": row[11], "created_at": row[12]
                    })
                return result
    except Exception as e:
        logger.error(f"get_all_active_dingshi err: {e}", exc_info=True)
        return []


async def update_dingshi_last_sent(dingshi_id: int, date_val, datetime_val=None):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE group_dingshi SET last_sent_date = %s, last_sent_at = %s WHERE id = %s", (date_val, datetime_val, dingshi_id))
    except Exception as e:
        logger.error(f"update_dingshi_last_sent err: {e}", exc_info=True)


def parse_days(days_str: str) -> list:
    if not days_str:
        return [1, 2, 3, 4, 5, 6, 7]
    ds = days_str.strip()
    special_map = {"每天": [1, 2, 3, 4, 5, 6, 7], "工作日": [1, 2, 3, 4, 5], "周末": [6, 7], "*": [1, 2, 3, 4, 5, 6, 7]}
    if ds in special_map:
        return special_map[ds]
    days = []
    for part in ds.split(","):
        part = part.strip()
        day_map = {"周一": 1, "周二": 2, "周三": 3, "周四": 4, "周五": 5, "周六": 6, "周日": 7, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7}
        if part in day_map:
            days.append(day_map[part])
    return days if days else [1, 2, 3, 4, 5, 6, 7]


def should_send_today(schedule_days: str, current_weekday: int) -> bool:
    days = parse_days(schedule_days)
    return current_weekday in days


def format_days_display(days_str: str) -> str:
    if not days_str:
        return "每天"
    ds = days_str.strip()
    display_map = {"*": "每天", "每天": "每天", "工作日": "工作日", "周末": "周末"}
    if ds in display_map:
        return display_map[ds]
    days = parse_days(ds)
    day_names = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
    return " ".join(day_names[d] for d in days)


async def get_dingshi_list_text(chat_id: str, dingshi_list: list, user_id: int = 0) -> str:
    title = await t(user_id, "dingshi_title") if user_id else "定时消息管理"
    desc = await t(user_id, "dingshi_desc") if user_id else "设置后，机器人将在指定时间自动发送消息到本群。"
    no_data = await t(user_id, "dingshi_no_data") if user_id else "暂无定时消息，点击下方按钮添加。"
    text_parts = [f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>{title}</b>\n{desc}\n']
    if not dingshi_list:
        text_parts.append(f'\n{EMOJI_WARN} {no_data}')
    else:
        for idx, item in enumerate(dingshi_list, 1):
            status_icon = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item["status"] else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
            interval_mins = item.get("interval_minutes", 0) or 0
            if interval_mins > 0:
                time_str = f'每{interval_mins}分钟'
                days_str = ''
            else:
                time_str = item["schedule_time"]
                days_str = f' | {format_days_display(item.get("schedule_days", "*"))}'
            has_text = f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji>' if item.get("content_text") else ""
            has_media = f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">📷</tg-emoji>' if item.get("media_file_id") else ""
            has_btn = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji>' if item.get("buttons_text") else ""
            extras = " ".join(filter(None, [has_text, has_media, has_btn]))
            text_parts.append(f'\n{idx}. {status_icon} <b>{time_str}</b>{days_str} {extras}')
    return "".join(text_parts)


def get_dingshi_list_keyboard(chat_id: str, dingshi_list: list, lang: str = DEFAULT_LANG, is_channel: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    for item in dingshi_list:
        status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
        interval_mins = item.get("interval_minutes", 0) or 0
        label = f'每{interval_mins}分钟' if interval_mins > 0 else item["schedule_time"]
        row = [
            InlineKeyboardButton(label, callback_data=f"dingshi_detail_{chat_id}_{item['id']}", icon_custom_emoji_id=CLOCK_EMOJI_ID),
            InlineKeyboardButton(t_sync(lang, "enable_btn") if item["status"] else t_sync(lang, "disable_btn"), callback_data=f"dingshi_toggle_{chat_id}_{item['id']}", icon_custom_emoji_id=status_icon),
            InlineKeyboardButton(t_sync(lang, "delete_short"), callback_data=f"dingshi_delete_{chat_id}_{item['id']}", icon_custom_emoji_id=DELETE_EMOJI_ID)
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t_sync(lang, "dingshi_add"), callback_data=f"dingshi_add_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID)])
    if is_channel:
        keyboard.append([InlineKeyboardButton("« " + t_sync(lang, "back_channel_list"), callback_data=f"manage_channel_{chat_id}")])
    else:
        keyboard.append([InlineKeyboardButton("« " + t_sync(lang, "back_group_manage"), callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_dingshi_detail_text(item: dict, lang: str = DEFAULT_LANG) -> str:
    status_text = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> {t_sync(lang, "enable")}' if item["status"] else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji> {t_sync(lang, "disable")}'
    interval_mins = item.get("interval_minutes", 0) or 0
    if interval_mins > 0:
        time_line = f'<b>发送间隔</b> 每{interval_mins}分钟'
        day_line = ''
    else:
        time_line = f'<b>发送时间</b> {item["schedule_time"]}'
        days_str = format_days_display(item.get("schedule_days", "*"))
        day_line = f'<b>发送周期</b> {days_str}'
    has_media = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item.get("media_file_id") else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    has_buttons = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item.get("buttons_text") else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    has_text = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item.get("content_text") else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    parts = [
        f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>{t_sync(lang, "dingshi_detail")}</b>\n',
        f'<b>{t_sync(lang, "status_label")}</b> {status_text}',
        time_line,
        f'<b>{t_sync(lang, "text_label")}</b> {has_text}',
        f'<b>{t_sync(lang, "media_label")}</b> {has_media}',
        f'<b>{t_sync(lang, "btn_label")}</b> {has_buttons}'
    ]
    if day_line:
        parts.insert(3, day_line)
    return "\n".join(parts)


def get_dingshi_detail_keyboard(chat_id: str, dingshi_id: int, item: dict, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
    keyboard = [
        [InlineKeyboardButton(t_sync(lang, "close_btn") if item["status"] else t_sync(lang, "open_btn"), callback_data=f"dingshi_toggle_{chat_id}_{dingshi_id}", icon_custom_emoji_id=CROSS_EMOJI_ID if item["status"] else CHECK_EMOJI_ID)],
        [InlineKeyboardButton(t_sync(lang, "edit_text_btn"), callback_data=f"dingshi_edit_text_{chat_id}_{dingshi_id}", icon_custom_emoji_id=TEXT_EMOJI_ID),
         InlineKeyboardButton(t_sync(lang, "edit_media_btn"), callback_data=f"dingshi_edit_media_{chat_id}_{dingshi_id}", icon_custom_emoji_id=MEDIA_EMOJI_ID)],
        [InlineKeyboardButton(t_sync(lang, "edit_btn_btn"), callback_data=f"dingshi_edit_btn_{chat_id}_{dingshi_id}", icon_custom_emoji_id=BTN_EMOJI_ID),
         InlineKeyboardButton(t_sync(lang, "dingshi_edit_time"), callback_data=f"dingshi_edit_time_{chat_id}_{dingshi_id}", icon_custom_emoji_id=CLOCK_EMOJI_ID)],
        [InlineKeyboardButton(t_sync(lang, "preview"), callback_data=f"dingshi_preview_{chat_id}_{dingshi_id}", icon_custom_emoji_id=PREVIEW_EMOJI_ID)],
        [InlineKeyboardButton(t_sync(lang, "dingshi_del"), callback_data=f"dingshi_delete_{chat_id}_{dingshi_id}", icon_custom_emoji_id=DELETE_EMOJI_ID)],
        [InlineKeyboardButton("« " + t_sync(lang, "dingshi_back_list"), callback_data=f"group_dingshi_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_dingshi_panel(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_chat_id: int, user_id: int = 0):
    dingshi_list = await get_dingshi_list(chat_id)
    text = await get_dingshi_list_text(str(chat_id), dingshi_list, user_id)
    # 检测聊天类型，使返回按钮能正确跳转到群组管理或频道管理
    try:
        from telegram import Chat
        chat = await context.bot.get_chat(chat_id)
        is_channel = (chat.type == Chat.CHANNEL)
    except Exception:
        is_channel = False
    reply_markup = get_dingshi_list_keyboard(str(chat_id), dingshi_list, is_channel=is_channel)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def send_dingshi_detail_panel(context: ContextTypes.DEFAULT_TYPE, chat_id: str, dingshi_id: int, target_chat_id: int):
    item = await get_dingshi_by_id(dingshi_id)
    if not item:
        await context.bot.send_message(chat_id=target_chat_id, text=f"{EMOJI_ERROR} 该定时消息不存在或已被删除。")
        return
    text = get_dingshi_detail_text(item)
    reply_markup = get_dingshi_detail_keyboard(chat_id, dingshi_id, item)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def send_dingshi_message(bot, chat_id: int, item: dict):
    try:
        content_text = item.get("content_text") or ""
        buttons_text = item.get("buttons_text")
        media_type = item.get("media_type")
        media_file_id = item.get("media_file_id")
        reply_markup = parse_welcome_buttons(buttons_text)
        if media_type == "photo" and media_file_id:
            await bot.send_photo(chat_id=chat_id, photo=media_file_id, caption=content_text, parse_mode="HTML", reply_markup=reply_markup)
        elif media_type == "video" and media_file_id:
            await bot.send_video(chat_id=chat_id, video=media_file_id, caption=content_text, parse_mode="HTML", reply_markup=reply_markup)
        elif media_type == "document" and media_file_id:
            await bot.send_document(chat_id=chat_id, document=media_file_id, caption=content_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text=content_text, parse_mode="HTML", reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.error(f"send_dingshi_message err for chat {chat_id}, dingshi {item.get('id')}: {e}")
        return False


def _next_step(current_step: str) -> str:
    order = {"basic": "text", "text": "media", "media": "buttons", "buttons": None}
    return order.get(current_step)


async def _do_step_skip(context, chat_id: str, dingshi_id: int, current_step: str, target_chat_id: int, user_id: int):
    next_s = _next_step(current_step)
    if next_s is None:
        _AWAIT_DINGSHI_INPUT.pop(user_id, None)
        await context.bot.send_message(chat_id=target_chat_id, text=f'{EMOJI_SUCCESS} 定时消息设置完成！')
        await send_dingshi_detail_panel(context, chat_id, dingshi_id, target_chat_id)
        return
    _AWAIT_DINGSHI_INPUT[user_id] = {"type": next_s, "chat_id": chat_id, "dingshi_id": dingshi_id, "conv_chat": target_chat_id}
    kb = get_step_keyboard(chat_id, dingshi_id, next_s, show_clear=next_s in ("text", "media", "buttons"), show_skip=True)
    prompts = {
        "text": (f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>第二步：设置消息文本</b>\n\n支持 HTML 和文字字体格式（加粗、链接、删透、块引用、<b>自定义会员表情</b>等）\n\n请发送定时消息的文本内容：', True),
        "media": (f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">🖼</tg-emoji> <b>第三步：设置媒体附件（可选）</b>\n\n请发送图片、视频或文件（大小不超过 <b>5MB</b>）：', True),
        "buttons": (f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>第四步：设置按钮（可选）</b>\n\n格式：<b>颜色（可选）-按钮文字-链接</b>\n颜色可选：红色 / 绿色 / 蓝色（也可以只写 红 / 绿 / 蓝）\n用 <b>&&</b> 分隔同行，<b>换行</b>分行\n\n示例：\n<code>蓝色-官方频道-https://t.me/channel</code>\n<code>红色-按钮1-https://a.com && 绿色-按钮2-https://b.com</code>：', True),
    }
    prompt, has_skip = prompts[next_s]
    await context.bot.send_message(chat_id=target_chat_id, text=prompt, parse_mode="HTML", reply_markup=kb)


async def _do_step_clear(context, chat_id: str, dingshi_id: int, current_step: str, target_chat_id: int, user_id: int):
    if current_step == "text":
        await update_dingshi(dingshi_id, content_text="")
    elif current_step == "media":
        await update_dingshi(dingshi_id, media_type="", media_file_id="")
    elif current_step == "buttons":
        await update_dingshi(dingshi_id, buttons_text="")
    _AWAIT_DINGSHI_INPUT.pop(user_id, None)
    await context.bot.send_message(chat_id=target_chat_id, text=f'{EMOJI_SUCCESS} 已清空！')
    await send_dingshi_detail_panel(context, chat_id, dingshi_id, target_chat_id)


async def dingshi_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    if data.startswith("dingshi_skip_") or data.startswith("dingshi_clear_"):
        try:
            group_chat_id = _extract_group_chat_id(data)
            member = await context.bot.get_chat_member(group_chat_id, user.id)
            if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                await query.answer("⚠️ 只有管理员才能管理定时消息。", show_alert=True)
                return
        except Exception:
            return
        step = data.split("_")[2]
        parts = data.split("_")
        chat_id = parts[3]
        dingshi_id = int(parts[4])
        if data.startswith("dingshi_skip_"):
            await query.answer()
            await query.message.delete()
            await _do_step_skip(context, chat_id, dingshi_id, step, update.effective_chat.id, user_id)
        elif data.startswith("dingshi_clear_"):
            await query.answer()
            await query.message.delete()
            await _do_step_clear(context, chat_id, dingshi_id, step, update.effective_chat.id, user_id)
        return

    try:
        group_chat_id = _extract_group_chat_id(data)
        member = await context.bot.get_chat_member(group_chat_id, user.id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能管理定时消息。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("group_dingshi_"):
        chat_id = data.split("_")[2]
        await query.answer()
        await query.message.delete()
        await send_dingshi_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("dingshi_add_"):
        chat_id = data.split("_")[2]
        await query.answer()
        _AWAIT_DINGSHI_INPUT[user_id] = {"type": "basic", "chat_id": chat_id, "conv_chat": update.effective_chat.id}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_dingshi_{chat_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>添加定时消息</b>\n\n'
            f'<b>每日定时：</b>\n<code>HH:MM|周期</code>\n'
            f'周期可选：<b>每天</b>、<b>工作日</b>、<b>周末</b>、或指定星期（如 <b>周一,周三,周五</b>）\n'
            f'示例：<code>08:00|每天</code>、<code>20:30|工作日</code>\n\n'
            f'<b>间隔发送：</b>\n<code>每X分钟</code>\n'
            f'示例：<code>每5分钟</code>、<code>每30分钟</code>',
            reply_markup=kb
        )
        return

    if data.startswith("dingshi_detail_"):
        parts = data.split("_")
        chat_id = parts[2]
        dingshi_id = int(parts[3])
        await query.answer()
        await query.message.delete()
        await send_dingshi_detail_panel(context, chat_id, dingshi_id, update.effective_chat.id)
        return

    if data.startswith("dingshi_toggle_"):
        parts = data.split("_")
        chat_id = parts[2]
        dingshi_id = int(parts[3])
        new_status = await toggle_dingshi_status(dingshi_id)
        await query.answer(f"{'✅ 已开启' if new_status else '❌ 已关闭'}")
        item = await get_dingshi_by_id(dingshi_id)
        if item:
            await query.edit_message_text(text=get_dingshi_detail_text(item), parse_mode="HTML", reply_markup=get_dingshi_detail_keyboard(chat_id, dingshi_id, item))
        return

    if data.startswith("dingshi_delete_"):
        parts = data.split("_")
        chat_id = parts[2]
        dingshi_id = int(parts[3])
        await delete_dingshi(dingshi_id)
        await query.answer("已删除")
        await query.message.delete()
        await send_dingshi_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("dingshi_edit_text_"):
        parts = data.split("_")
        chat_id = parts[3]
        dingshi_id = int(parts[4])
        item = await get_dingshi_by_id(dingshi_id)
        current_text = item.get("content_text") or "未设置"
        await query.answer()
        _AWAIT_DINGSHI_INPUT[user_id] = {"type": "text", "chat_id": chat_id, "dingshi_id": dingshi_id, "conv_chat": update.effective_chat.id}
        kb = get_step_keyboard(chat_id, dingshi_id, "text", show_clear=True, show_skip=False)
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>编辑定时消息文本</b>\n\n'
            f'支持 HTML 和文字字体格式（加粗、链接、删透、块引用、<b>自定义会员表情</b>等）\n\n'
            f'当前内容：\n<blockquote expandable>{current_text[:200]}</blockquote>\n\n请发送新的文本内容：',
            reply_markup=kb
        )
        return

    if data.startswith("dingshi_edit_media_"):
        parts = data.split("_")
        chat_id = parts[3]
        dingshi_id = int(parts[4])
        await query.answer()
        _AWAIT_DINGSHI_INPUT[user_id] = {"type": "media", "chat_id": chat_id, "dingshi_id": dingshi_id, "conv_chat": update.effective_chat.id}
        kb = get_step_keyboard(chat_id, dingshi_id, "media", show_clear=True, show_skip=True)
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">🖼</tg-emoji> <b>编辑定时消息媒体</b>\n\n'
            f'请发送图片、视频或文件（大小不超过 <b>5MB</b>）',
            reply_markup=kb
        )
        return

    if data.startswith("dingshi_edit_btn_"):
        parts = data.split("_")
        chat_id = parts[3]
        dingshi_id = int(parts[4])
        await query.answer()
        _AWAIT_DINGSHI_INPUT[user_id] = {"type": "buttons", "chat_id": chat_id, "dingshi_id": dingshi_id, "conv_chat": update.effective_chat.id}
        kb = get_step_keyboard(chat_id, dingshi_id, "buttons", show_clear=True, show_skip=True)
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>编辑定时消息按钮</b>\n\n'
            f'格式：<b>颜色（可选）-按钮文字-链接</b>\n'
            f'颜色可选：红色 / 绿色 / 蓝色（也可以只写 红 / 绿 / 蓝）\n'
            f'用 <b>&&</b> 分隔同行按钮，<b>换行</b>分行\n\n'
            f'示例：\n<code>蓝色-官方频道-https://t.me/channel</code>\n'
            f'<code>红色-按钮1-https://a.com && 绿色-按钮2-https://b.com</code>',
            reply_markup=kb
        )
        return

    if data.startswith("dingshi_edit_time_"):
        parts = data.split("_")
        chat_id = parts[3]
        dingshi_id = int(parts[4])
        item = await get_dingshi_by_id(dingshi_id)
        interval_mins = item.get("interval_minutes", 0) or 0
        if interval_mins > 0:
            current = f'每{interval_mins}分钟'
        else:
            current = f'{item["schedule_time"]}|{format_days_display(item.get("schedule_days", "*"))}'
        await query.answer()
        _AWAIT_DINGSHI_INPUT[user_id] = {"type": "basic", "chat_id": chat_id, "dingshi_id": dingshi_id, "conv_chat": update.effective_chat.id}
        kb = get_step_keyboard(chat_id, dingshi_id, "basic", show_clear=False, show_skip=False)
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>修改发送时间</b>\n\n'
            f'当前设置：<code>{current}</code>\n\n请发送新的时间设置：\n'
            f'每日定时：<code>HH:MM|周期</code>\n'
            f'间隔发送：<code>每X分钟</code>',
            reply_markup=kb
        )
        return

    if data.startswith("dingshi_preview_"):
        parts = data.split("_")
        chat_id = parts[2]
        dingshi_id = int(parts[3])
        item = await get_dingshi_by_id(dingshi_id)
        if not item:
            await query.answer("该定时消息不存在", show_alert=True)
            return
        if not item.get("content_text") and not item.get("media_file_id"):
            await query.answer("暂无内容可预览", show_alert=True)
            return
        await query.answer("正在发送预览...")
        success = await send_dingshi_message(context.bot, update.effective_chat.id, item)
        if not success:
            await query.message.reply_html(f'{EMOJI_WARN} 预览发送失败，请检查内容设置。')
        return

    if data.startswith("dingshi_cancel_"):
        parts = data.split("_")
        chat_id = parts[2]
        _AWAIT_DINGSHI_INPUT.pop(user_id, None)
        await query.answer("已取消")
        await query.message.delete()
        await send_dingshi_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return


async def dingshi_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    await_data = _AWAIT_DINGSHI_INPUT.get(user_id)
    logger.info(f"dingshi_input_handler called, await_data={'set' if await_data else 'None'}, user={user_id}")
    if not await_data:
        return
    # 只消费在发起设置的同一会话里的消息，避免把其他会话的普通发言当成设置输入
    if update.effective_chat is None or update.effective_chat.id != await_data.get("conv_chat"):
        return
    try:
        chat_id = int(await_data["chat_id"])
        input_type = await_data["type"]
        dingshi_id = await_data.get("dingshi_id", 0)
        message = update.message
        if message is None:
            return

        if input_type == "basic":
            if not message.text:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "basic", show_skip=False, show_clear=False)
                await message.reply_html(f'{EMOJI_WARN} 请发送文本格式的时间设置，如：<code>08:00|每天</code> 或 <code>每5分钟</code>', reply_markup=kb)
                return
            raw_text = message.text.strip()

            # 间隔模式：每X分钟 / 每X分
            interval_match = re.match(r'^每\s*(\d+)\s*(分钟|分)$', raw_text)
            if interval_match:
                interval_mins = int(interval_match.group(1))
                if interval_mins < 1 or interval_mins > 1440:
                    kb = get_step_keyboard(str(chat_id), dingshi_id, "basic", show_skip=False, show_clear=False)
                    await message.reply_html(f'{EMOJI_WARN} 间隔分钟数需在 1-1440 之间（1分钟 至 24小时）。', reply_markup=kb)
                    return
                if dingshi_id:
                    await update_dingshi(dingshi_id, schedule_time="", schedule_days="*", interval_minutes=interval_mins)
                    _AWAIT_DINGSHI_INPUT.pop(user_id, None)
                    await message.reply_html(f'{EMOJI_SUCCESS} 已设置为每隔 <b>{interval_mins}</b> 分钟发送！')
                    await send_dingshi_detail_panel(context, str(chat_id), dingshi_id, update.effective_chat.id)
                else:
                    new_id = await create_dingshi(chat_id, "", "*", interval_mins)
                    if new_id:
                        _AWAIT_DINGSHI_INPUT[user_id] = {"type": "text", "chat_id": str(chat_id), "dingshi_id": new_id, "conv_chat": update.effective_chat.id}
                        kb = get_step_keyboard(str(chat_id), new_id, "text", show_clear=False, show_skip=True)
                        await message.reply_html(
                            f'{EMOJI_SUCCESS} 间隔设置成功（每 <b>{interval_mins}</b> 分钟）！\n\n'
                            f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>第二步：设置消息文本</b>\n\n'
                            f'支持 HTML 和文字字体格式（加粗、链接、删透、块引用、<b>自定义会员表情</b>等）\n\n'
                            f'请发送定时消息的文本内容：',
                            reply_markup=kb
                        )
                    else:
                        await message.reply_html(f'{EMOJI_ERROR} 创建失败，请重试。')
                return

            # 每日定时模式：HH:MM|周期
            match = re.match(r'^(\d{1,2}):(\d{2})\|(.+)$', raw_text)
            if not match:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "basic", show_skip=False, show_clear=False)
                await message.reply_html(f'{EMOJI_WARN} 格式错误！\n每日定时：<code>HH:MM|周期</code>（如 <code>08:00|每天</code>）\n间隔发送：<code>每X分钟</code>（如 <code>每5分钟</code>）', reply_markup=kb)
                return
            hour = int(match.group(1))
            minute = int(match.group(2))
            days_raw = match.group(3).strip()
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "basic", show_skip=False, show_clear=False)
                await message.reply_html(f'{EMOJI_WARN} 时间格式错误！小时 0-23，分钟 0-59。', reply_markup=kb)
                return
            valid_days = parse_days(days_raw)
            if not valid_days:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "basic", show_skip=False, show_clear=False)
                await message.reply_html(f'{EMOJI_WARN} 周期格式错误！可选：每天、工作日、周末、周一,周三 等。', reply_markup=kb)
                return
            schedule_time = f"{hour:02d}:{minute:02d}"
            if dingshi_id:
                await update_dingshi(dingshi_id, schedule_time=schedule_time, schedule_days=days_raw, interval_minutes=0)
                _AWAIT_DINGSHI_INPUT.pop(user_id, None)
                await message.reply_html(f'{EMOJI_SUCCESS} 发送时间已更新！')
                await send_dingshi_detail_panel(context, str(chat_id), dingshi_id, update.effective_chat.id)
            else:
                new_id = await create_dingshi(chat_id, schedule_time, days_raw)
                if new_id:
                    _AWAIT_DINGSHI_INPUT[user_id] = {"type": "text", "chat_id": str(chat_id), "dingshi_id": new_id, "conv_chat": update.effective_chat.id}
                    kb = get_step_keyboard(str(chat_id), new_id, "text", show_clear=False, show_skip=True)
                    await message.reply_html(
                        f'{EMOJI_SUCCESS} 时间设置成功！\n\n'
                        f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>第二步：设置消息文本</b>\n\n'
                        f'支持 HTML 和文字字体格式（加粗、链接、删透、块引用、<b>自定义会员表情</b>等）\n\n'
                        f'请发送定时消息的文本内容：',
                        reply_markup=kb
                    )
                else:
                    await message.reply_html(f'{EMOJI_ERROR} 创建失败，请重试。')
            return

        if input_type == "text":
            if not message.text:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "text", show_clear=bool(dingshi_id), show_skip=True)
                await message.reply_html(f'{EMOJI_WARN} 请发送文本消息内容。', reply_markup=kb)
                return
            raw_text = message.text.strip()
            new_text = get_message_html(message)
            await update_dingshi(dingshi_id, content_text=new_text)
            _AWAIT_DINGSHI_INPUT[user_id] = {"type": "media", "chat_id": str(chat_id), "dingshi_id": dingshi_id, "conv_chat": update.effective_chat.id}
            kb = get_step_keyboard(str(chat_id), dingshi_id, "media", show_clear=bool(dingshi_id), show_skip=True)
            await message.reply_html(
                f'{EMOJI_SUCCESS} 文本内容已设置！\n\n'
                f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">🖼</tg-emoji> <b>第三步：设置媒体附件（可选）</b>\n\n'
                f'请发送图片、视频或文件（大小不超过 <b>5MB</b>）：',
                reply_markup=kb
            )
            return

        if input_type == "media":
            raw_text = (message.text or message.caption or "").strip()
            media_type = None
            media_file_id = None
            file_size = 0
            if message.photo:
                photo = message.photo[-1]
                file_size = photo.file_size or 0
                media_type = "photo"
                media_file_id = photo.file_id
            elif message.video:
                video = message.video
                file_size = video.file_size or 0
                media_type = "video"
                media_file_id = video.file_id
            elif message.document:
                doc = message.document
                file_size = doc.file_size or 0
                media_type = "document"
                media_file_id = doc.file_id
            else:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "media", show_clear=bool(dingshi_id), show_skip=True)
                await message.reply_html(f'{EMOJI_WARN} 未识别到有效的图片、视频或文件，请重新发送！', reply_markup=kb)
                return
            if file_size > 5 * 1024 * 1024:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "media", show_clear=bool(dingshi_id), show_skip=True)
                await message.reply_html(f'{EMOJI_WARN} 文件大小超过 <b>5MB</b> 限制，请处理后重新发送！', reply_markup=kb)
                return
            await update_dingshi(dingshi_id, media_type=media_type, media_file_id=media_file_id)
            _AWAIT_DINGSHI_INPUT[user_id] = {"type": "buttons", "chat_id": str(chat_id), "dingshi_id": dingshi_id, "conv_chat": update.effective_chat.id}
            kb = get_step_keyboard(str(chat_id), dingshi_id, "buttons", show_clear=bool(dingshi_id), show_skip=True)
            await message.reply_html(
                f'{EMOJI_SUCCESS} 媒体附件已设置！\n\n'
                f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>第四步：设置按钮（可选）</b>\n\n'
                f'格式：<b>颜色（可选）-按钮文字-链接</b>\n'
                f'颜色可选：红色 / 绿色 / 蓝色（也可以只写 红 / 绿 / 蓝）\n'
                f'用 <b>&&</b> 分隔同行，<b>换行</b>分行',
                reply_markup=kb
            )
            return

        if input_type == "buttons":
            if not message.text:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "buttons", show_clear=bool(dingshi_id), show_skip=True)
                await message.reply_html(f'{EMOJI_WARN} 请发送按钮配置文本。', reply_markup=kb)
                return
            raw_text = message.text.strip()
            processed_text = preprocess_button_text(message)
            markup = parse_welcome_buttons(processed_text)
            if not markup:
                kb = get_step_keyboard(str(chat_id), dingshi_id, "buttons", show_clear=bool(dingshi_id), show_skip=True)
                await message.reply_html(f'{EMOJI_WARN} 按钮格式错误，请参照示例重新输入！', reply_markup=kb)
                return
            await update_dingshi(dingshi_id, buttons_text=processed_text)
            _AWAIT_DINGSHI_INPUT.pop(user_id, None)
            await message.reply_html(f'{EMOJI_SUCCESS} 按钮已设置！定时消息设置完成。')
            await send_dingshi_detail_panel(context, str(chat_id), dingshi_id, update.effective_chat.id)
            return

    except Exception as e:
        logger.error(f"dingshi_input_handler err: {e}", exc_info=True)
        try:
            await update.message.reply_html(f'{EMOJI_ERROR} 处理失败：{e}')
        except Exception:
            pass


async def dingshi_scheduler(context: ContextTypes.DEFAULT_TYPE):
    try:
        now_utc = datetime.datetime.utcnow()
        active_list = await get_all_active_dingshi()
        # 按群缓存时区偏移，避免对同一群重复查询
        _tz_cache = {}
        for item in active_list:
            try:
                chat_id = item["chat_id"]
                # 获取该群群主的时区偏移
                if chat_id not in _tz_cache:
                    from database import get_user_timezone
                    offset = 8  # 默认 UTC+8
                    try:
                        admins = await context.bot.get_chat_administrators(chat_id)
                        owner = next((a.user for a in admins if a.status == "creator"), None)
                        if owner:
                            tz_str = await get_user_timezone(owner.id)
                            import re as _re
                            m = _re.search(r'UTC([+-]\d+)', tz_str)
                            if m:
                                offset = int(m.group(1))
                    except Exception:
                        pass
                    _tz_cache[chat_id] = offset
                offset = _tz_cache[chat_id]
                now_local = now_utc + datetime.timedelta(hours=offset)
                current_time = now_local.strftime("%H:%M")
                current_weekday = now_local.isoweekday()
                today_date = now_local.date()

                interval_mins = item.get("interval_minutes", 0) or 0

                if interval_mins > 0:
                    # 间隔模式：检查距离上次发送是否已满 interval_minutes
                    last_sent_at = item.get("last_sent_at")
                    if last_sent_at and isinstance(last_sent_at, datetime.datetime):
                        elapsed = (now_local - last_sent_at).total_seconds()
                        if elapsed < interval_mins * 60:
                            continue
                else:
                    # 每日定时模式
                    if item["schedule_time"] != current_time:
                        continue
                    if not should_send_today(item.get("schedule_days", "*"), current_weekday):
                        continue
                    last_sent = item.get("last_sent_date")
                    if last_sent and last_sent == today_date:
                        continue

                if not item.get("content_text") and not item.get("media_file_id"):
                    continue
                success = await send_dingshi_message(context.bot, chat_id, item)
                if success:
                    await update_dingshi_last_sent(item["id"], today_date, now_local)
                    if interval_mins > 0:
                        logger.info(f"dingshi sent (interval={interval_mins}m): id={item['id']} chat={chat_id}")
                    else:
                        logger.info(f"dingshi sent: id={item['id']} chat={chat_id} time={current_time} tz=UTC{offset:+d}")
            except Exception as e:
                logger.error(f"dingshi_scheduler item err id={item.get('id')}: {e}")
    except Exception as e:
        logger.error(f"dingshi_scheduler err: {e}", exc_info=True)


async def run_dingshi_scheduler(application):
    await asyncio.sleep(10)
    while True:
        try:
            await dingshi_scheduler(application)
        except Exception as e:
            logger.error(f"run_dingshi_scheduler err: {e}", exc_info=True)
        await asyncio.sleep(60)
