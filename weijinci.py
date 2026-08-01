import asyncio
import logging
import datetime
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
import database
from lang import t

logger = logging.getLogger(__name__)
logger.info("weijinci module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
ADD_EMOJI_ID = "5775937998948404844"
BACK_EMOJI_ID = "5875082500023258804"
DELETE_EMOJI_ID = "6017288111279575194"
WARN_EMOJI_ID = "5447644880824181073"
SHIELD_EMOJI_ID = "5931409969613116639"
LOCK_EMOJI_ID = "5879895758202735862"
BELL_EMOJI_ID = "5909201569898827582"
BLOCK_EMOJI_ID = "5886285363869126932"

EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

_AWAIT_WEIJINCI_INPUT = {}

MUTE_DURATIONS = [(3600, "禁言1小时"), (21600, "禁言6小时"), (86400, "禁言1天"), (604800, "禁言1周")]


def format_penalty_display(penalty: str, mute_duration: int = 3600) -> str:
    if penalty == "mute":
        for dur, label in MUTE_DURATIONS:
            if mute_duration == dur:
                return label
        return f"禁言{mute_duration}秒"
    return {"delete": "仅删除消息", "kick": "踢出群组", "ban": "永久封禁"}.get(penalty, penalty)


def _extract_group_chat_id(data: str) -> int:
    return int(data.split("_")[2])


def _parse_penalty_from_callback(data: str) -> tuple:
    parts = data.split("_")
    if parts[-1].isdigit() and len(parts) >= 2 and parts[-2] == "mute":
        return ("mute", int(parts[-1]))
    return (parts[-1], 0)


async def get_weijinci_list(chat_id: int) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, word, penalty, mute_duration, status, created_at FROM group_weijinci WHERE chat_id = %s ORDER BY id ASC",
                    (chat_id,))
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    result.append({"id": row[0], "chat_id": row[1], "word": row[2], "penalty": row[3],
                                   "mute_duration": row[4] or 3600, "status": bool(row[5]), "created_at": row[6]})
                return result
    except Exception as e:
        logger.error(f"get_weijinci_list err: {e}", exc_info=True)
        return []


async def add_weijinci(chat_id: int, word: str, penalty: str = "delete", mute_duration: int = 3600) -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO group_weijinci (chat_id, word, penalty, mute_duration) VALUES (%s, %s, %s, %s)",
                    (chat_id, word, penalty, mute_duration))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"add_weijinci err: {e}", exc_info=True)
        return 0


async def delete_weijinci(word_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM group_weijinci WHERE id = %s", (word_id,))
    except Exception as e:
        logger.error(f"delete_weijinci err: {e}", exc_info=True)


async def toggle_weijinci_status(word_id: int) -> bool:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM group_weijinci WHERE id = %s", (word_id,))
                row = await cur.fetchone()
                if row:
                    new_status = not bool(row[0])
                    await cur.execute("UPDATE group_weijinci SET status = %s WHERE id = %s", (new_status, word_id))
                    return new_status
    except Exception as e:
        logger.error(f"toggle_weijinci_status err: {e}", exc_info=True)
    return False


async def update_weijinci_penalty(word_id: int, penalty: str):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE group_weijinci SET penalty = %s WHERE id = %s", (penalty, word_id))
    except Exception as e:
        logger.error(f"update_weijinci_penalty err: {e}", exc_info=True)


async def get_active_weijinci(chat_id: int) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, word, penalty, mute_duration FROM group_weijinci WHERE chat_id = %s AND status = TRUE",
                    (chat_id,))
                rows = await cur.fetchall()
                return [{"id": row[0], "word": row[1], "penalty": row[2], "mute_duration": row[3] or 3600} for row in rows]
    except Exception as e:
        logger.error(f"get_active_weijinci err: {e}", exc_info=True)
        return []


async def get_weijinci_list_text(chat_id: str, items: list, user_id: int = 0) -> str:
    title = await t(user_id, "weijinci_title") if user_id else "违禁词管理"
    desc = await t(user_id, "weijinci_desc") if user_id else "设置违禁词后，包含违禁词的消息将被自动处理。"
    no_data = await t(user_id, "weijinci_no_data") if user_id else "暂无违禁词，点击下方按钮添加。"
    text = f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>{title}</b>\n{desc}\n'
    if not items:
        text += f'\n{EMOJI_WARN} {no_data}'
    else:
        for idx, item in enumerate(items, 1):
            status_icon = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item["status"] else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
            penalty_text = format_penalty_display(item["penalty"], item.get("mute_duration", 3600))
            text += f'\n{idx}. {status_icon} <b>{item["word"]}</b> — {penalty_text}'
    return text


def get_weijinci_list_keyboard(chat_id: str, items: list) -> InlineKeyboardMarkup:
    keyboard = []
    for item in items:
        status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
        row = [
            InlineKeyboardButton(item["word"], callback_data=f"weijinci_penalty_{chat_id}_{item['id']}", icon_custom_emoji_id=SHIELD_EMOJI_ID),
            InlineKeyboardButton("关闭" if item["status"] else "开启", callback_data=f"weijinci_toggle_{chat_id}_{item['id']}", icon_custom_emoji_id=status_icon),
            InlineKeyboardButton("删", callback_data=f"weijinci_delete_{chat_id}_{item['id']}", icon_custom_emoji_id=DELETE_EMOJI_ID)
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("添加违禁词", callback_data=f"weijinci_add_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_addpenalty_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("仅删除消息", callback_data=f"weijinci_setpenalty_{chat_id}_delete", icon_custom_emoji_id=LOCK_EMOJI_ID)],
    ]
    for dur, label in MUTE_DURATIONS:
        keyboard.append([InlineKeyboardButton(label, callback_data=f"weijinci_setpenalty_{chat_id}_mute_{dur}", icon_custom_emoji_id=BELL_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("踢出群组", callback_data=f"weijinci_setpenalty_{chat_id}_kick", icon_custom_emoji_id=DELETE_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("永久封禁", callback_data=f"weijinci_setpenalty_{chat_id}_ban", icon_custom_emoji_id=BLOCK_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 取消", callback_data=f"group_weijinci_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_editpenalty_keyboard(chat_id: str, word_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("仅删除消息", callback_data=f"weijinci_dopenalty_{chat_id}_{word_id}_delete", icon_custom_emoji_id=LOCK_EMOJI_ID)],
    ]
    for dur, label in MUTE_DURATIONS:
        keyboard.append([InlineKeyboardButton(label, callback_data=f"weijinci_dopenalty_{chat_id}_{word_id}_mute_{dur}", icon_custom_emoji_id=BELL_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("踢出群组", callback_data=f"weijinci_dopenalty_{chat_id}_{word_id}_kick", icon_custom_emoji_id=DELETE_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("永久封禁", callback_data=f"weijinci_dopenalty_{chat_id}_{word_id}_ban", icon_custom_emoji_id=BLOCK_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"group_weijinci_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


async def send_weijinci_panel(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_chat_id: int, user_id: int = 0):
    items = await get_weijinci_list(chat_id)
    text = await get_weijinci_list_text(str(chat_id), items, user_id)
    reply_markup = get_weijinci_list_keyboard(str(chat_id), items)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def weijinci_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    chat_id = _extract_group_chat_id(data)

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能管理违禁词。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("group_weijinci_"):
        # 用户通过“取消”返回，清除挂起的输入等待状态
        _AWAIT_WEIJINCI_INPUT.pop(user_id, None)
        await query.answer()
        await query.message.delete()
        await send_weijinci_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("weijinci_add_"):
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>添加违禁词</b>\n\n请选择处罚方式：',
            parse_mode="HTML",
            reply_markup=get_addpenalty_keyboard(chat_id)
        )
        return

    if data.startswith("weijinci_toggle_"):
        word_id = int(data.split("_")[-1])
        new_status = await toggle_weijinci_status(word_id)
        await query.answer(f"{'✅ 已开启' if new_status else '❌ 已关闭'}")
        await query.message.delete()
        await send_weijinci_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("weijinci_delete_"):
        word_id = int(data.split("_")[-1])
        await delete_weijinci(word_id)
        await query.answer("已删除")
        await query.message.delete()
        await send_weijinci_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return

    if data.startswith("weijinci_penalty_"):
        word_id = int(data.split("_")[-1])
        await query.answer()
        await query.message.delete()
        items = await get_weijinci_list(int(chat_id))
        word_info = next((w for w in items if w["id"] == word_id), None)
        word_text = word_info["word"] if word_info else "未知"
        cur_penalty = word_info["penalty"] if word_info else "delete"
        cur_dur = word_info["mute_duration"] if word_info else 3600
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>修改处罚方式</b>\n\n违禁词：<b>{word_text}</b>\n当前处罚：<b>{format_penalty_display(cur_penalty, cur_dur)}</b>\n\n请选择新的处罚方式：',
            parse_mode="HTML",
            reply_markup=get_editpenalty_keyboard(chat_id, word_id)
        )
        return

    if data.startswith("weijinci_setpenalty_"):
        penalty, mute_duration = _parse_penalty_from_callback(data)
        penalty_text = format_penalty_display(penalty, mute_duration)
        _AWAIT_WEIJINCI_INPUT[user_id] = {"type": "add_word", "chat_id": chat_id, "penalty": penalty, "mute_duration": mute_duration, "conv_chat": update.effective_chat.id}
        await query.answer(f"处罚方式：{penalty_text}")
        await query.message.delete()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_weijinci_{chat_id}")]])
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">🛡</tg-emoji> <b>添加违禁词</b>\n\n处罚方式：<b>{penalty_text}</b>\n\n请发送要屏蔽的违禁词：',
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    if data.startswith("weijinci_dopenalty_"):
        parts = data.split("_")
        word_id = int(parts[3])
        penalty, mute_duration = _parse_penalty_from_callback(data)
        await update_weijinci_penalty(word_id, penalty)
        if mute_duration > 0:
            async with database.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("UPDATE group_weijinci SET mute_duration = %s WHERE id = %s", (mute_duration, word_id))
        penalty_text = format_penalty_display(penalty, mute_duration)
        await query.answer(f"已更新为：{penalty_text}")
        await query.message.delete()
        await send_weijinci_panel(context, int(chat_id), update.effective_chat.id, user_id)
        return


async def weijinci_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None:
            return
        await_data = _AWAIT_WEIJINCI_INPUT.get(user_id)
        logger.info(f"weijinci_input_handler called, await_data={'set' if await_data else 'None'}, user={user_id}")
        if not await_data:
            return
        # 只消费在发起设置的同一会话里的消息，避免把其他会话的普通发言当成设置输入
        if update.effective_chat is None or update.effective_chat.id != await_data.get("conv_chat"):
            return
        message = update.message
        if message is None or not message.text:
            return
        chat_id = int(await_data["chat_id"])
        word = message.text.strip()
        penalty = await_data.get("penalty", "delete")
        mute_duration = await_data.get("mute_duration", 0)
        new_id = await add_weijinci(chat_id, word, penalty, mute_duration)
        _AWAIT_WEIJINCI_INPUT.pop(user_id, None)
        if new_id:
            await message.reply_html(f'{EMOJI_SUCCESS} 违禁词 <b>{word}</b> 已添加！处罚：{format_penalty_display(penalty, mute_duration)}')
        else:
            await message.reply_html(f'{EMOJI_ERROR} 添加失败，请重试。')
        await send_weijinci_panel(context, chat_id, update.effective_chat.id, user_id)
    except Exception as e:
        logger.error(f"weijinci_input_handler err: {e}", exc_info=True)


async def weijinci_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检查消息是否包含违禁词，命中则删除+惩罚。返回 True 表示已拦截（调用方应停止后续处理）。"""
    try:
        if not update.message or not update.message.text:
            return False
        logger.info(f"weijinci_check_handler called, text={update.message.text[:30]}, chat={update.effective_chat.id}")
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if update.effective_user.is_bot:
            return False
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                return False
        except Exception:
            pass
        words = await get_active_weijinci(chat_id)
        if not words:
            return False
        msg_text = update.message.text.lower()
        matched = None
        for w in words:
            if w["word"].lower() in msg_text:
                matched = w
                break
        if not matched:
            return False
        try:
            await update.message.delete()
        except Exception:
            pass
        penalty = matched["penalty"]
        try:
            if penalty == "mute":
                until = datetime.datetime.utcnow() + datetime.timedelta(seconds=matched.get("mute_duration", 3600))
                await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False), until_date=until)
            elif penalty == "kick":
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            elif penalty == "ban":
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.error(f"weijinci penalty err: {e}")
        penalty_text = format_penalty_display(penalty, matched.get("mute_duration", 3600))
        try:
            user_mention = update.effective_user.mention_html()
            warn_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f'{EMOJI_WARN} {user_mention} 发送了违禁词 <b>{matched["word"]}</b>，已被{penalty_text}。',
                parse_mode="HTML"
            )
            asyncio.create_task(_delete_after(context.bot, chat_id, warn_msg.message_id, 10))
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"weijinci_check_handler err: {e}", exc_info=True)
        return False


async def _delete_after(bot, chat_id: int, msg_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
