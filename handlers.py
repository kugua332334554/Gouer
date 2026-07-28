import asyncio
import logging
import re
from datetime import datetime, timedelta
from telegram import Update, ChatMember, Chat, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import config
from database import (
    save_user,
    get_user_timezone,
    update_user_timezone,
    register_channel,
    register_supergroup,
    get_all_groups,
    get_all_channels,
    get_verify_settings,
    update_verify_settings,
    get_welcome_settings,
    get_points_settings,
    update_points_settings,
    get_user_points,
    update_user_points_direct,
    get_points_rank,
    log_group_action
)
from keyboards import (
    get_start_keyboard,
    get_timezone_keyboard,
    get_add_channel_keyboard,
    get_add_group_keyboard,
    get_private_chat_keyboard,
    get_pagination_keyboard,
    get_group_manage_keyboard,
    get_group_verification_keyboard,
    get_group_jifen_keyboard
)
from welcome import get_welcome_text, get_welcome_keyboard

logger = logging.getLogger(__name__)

EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_CHART = '<tg-emoji emoji-id="5931472654660800739">📊</tg-emoji>'
EMOJI_TROPHY = '<tg-emoji emoji-id="5226431245918942763">🏆</tg-emoji>'

async def auto_delete_message(bot, chat_id: int, message_id: int, delay: int = 300):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        pass

def get_verification_text(state: dict) -> str:
    status_text = f'{EMOJI_SUCCESS} 开启' if state['status'] else f'{EMOJI_ERROR} 关闭'
    penalty_text = "禁言" if state['penalty'] == 'mute' else "踢出"
    mode_map = {"button": "按钮", "math": "数学题", "captcha": "验证码"}
    mode_text = mode_map.get(state['mode'], state['mode'])
    return (
        f'<tg-emoji emoji-id="5931409969613116639">🛡</tg-emoji> <b>进群验证</b>\n\n'
        f'启用后，新用户需要完成验证，才能发送消息。\n\n'
        f'<tg-emoji emoji-id="5879585266426973039">🌐</tg-emoji> <b>状态:</b> {status_text}\n'
        f'<tg-emoji emoji-id="5879895758202735862">🔒</tg-emoji> <b>模式:</b> {mode_text}\n'
        f'<b>验证时间:</b> {state["duration"]} 分钟\n'
        f'<b>超时惩罚:</b> {penalty_text}'
    )

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await save_user(user.id, user.username, user.first_name)
    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = config.BOT_USERNAME
    args = context.args
    if args and len(args) > 0:
        param = args[0]
        if param == "group_panel":
            groups = await get_all_groups()
            text = config.ADD_QUN.replace("\\n", "\n").format(BOT_USERNAME=f"@{bot_username}")
            reply_markup = get_pagination_keyboard(groups, page=1, item_type="group", bot_username=bot_username, per_page=5)
            await update.message.reply_html(text=text, reply_markup=reply_markup)
            return
        elif param == "pindao_panel":
            channels = await get_all_channels()
            text = config.ADD_PIDANO.replace("\\n", "\n").format(BOT_USERNAME=f"@{bot_username}")
            reply_markup = get_pagination_keyboard(channels, page=1, item_type="channel", bot_username=bot_username, per_page=5)
            await update.message.reply_html(text=text, reply_markup=reply_markup)
            return
    text = config.START_MESSAGE.replace("\\n", "\n").format(
        USER=user.mention_html(),
        BOT_USERNAME=f"@{bot_username}"
    )
    await update.message.reply_html(text=text, reply_markup=get_start_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data
    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = config.BOT_USERNAME

    if data.startswith("unmute_btn_"):
        parts = data.split("_")
        target_id = int(parts[2])
        chat_id = int(parts[3])
        if not await _check_admin(update, context):
            await query.answer(f"{EMOJI_WARN} 只有管理员才能执行此操作。", show_alert=True)
            return
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
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
            await log_group_action(chat_id, target_id, "unmute_by_btn")
            await query.answer(f"{EMOJI_SUCCESS} 已解除禁言。", show_alert=True)
            await query.edit_message_text(
                text=f"{EMOJI_SUCCESS} 用户已由管理员 {user.mention_html()} 手动解禁。",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.answer(f"{EMOJI_ERROR} 解禁失败: {e}", show_alert=True)
        return

    if data == "channel":
        await query.answer()
        channels = await get_all_channels()
        text = config.ADD_PIDANO.replace("\\n", "\n").format(BOT_USERNAME=f"@{bot_username}")
        reply_markup = get_pagination_keyboard(channels, page=1, item_type="channel", bot_username=bot_username, per_page=5)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "group":
        await query.answer()
        groups = await get_all_groups()
        text = config.ADD_QUN.replace("\\n", "\n").format(BOT_USERNAME=f"@{bot_username}")
        reply_markup = get_pagination_keyboard(groups, page=1, item_type="group", bot_username=bot_username, per_page=5)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("page_"):
        await query.answer()
        _, item_type, page_str = data.split("_")
        page = int(page_str)
        if item_type == "group":
            items = await get_all_groups()
            text = config.ADD_QUN.replace("\\n", "\n").format(BOT_USERNAME=f"@{bot_username}")
        else:
            items = await get_all_channels()
            text = config.ADD_PIDANO.replace("\\n", "\n").format(BOT_USERNAME=f"@{bot_username}")
        reply_markup = get_pagination_keyboard(items, page=page, item_type=item_type, bot_username=bot_username, per_page=5)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "timezone":
        await query.answer()
        current_tz = await get_user_timezone(user_id)
        text = config.TIMEZONE_MESSAGE.replace("\\n", "\n").format(TIMEZONE=current_tz)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_timezone_keyboard())

    elif data.startswith("tz_"):
        new_tz = data.replace("tz_", "")
        await update_user_timezone(user_id, new_tz)
        await query.answer(f"时区已更新为: {new_tz}", show_alert=True)
        text = config.TIMEZONE_MESSAGE.replace("\\n", "\n").format(TIMEZONE=new_tz)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_timezone_keyboard())

    elif data == "back_to_main":
        await query.answer()
        text = config.START_MESSAGE.replace("\\n", "\n").format(USER=user.mention_html(), BOT_USERNAME=f"@{bot_username}")
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_start_keyboard())

    elif data.startswith("manage_group_"):
        await query.answer()
        chat_id = data.split("_")[2]
        text = '<tg-emoji emoji-id="5931409969613116639">🛡</tg-emoji> <b>群组管理面板</b>\n\n请选择你要设置的功能模块：'
        reply_markup = get_group_manage_keyboard(chat_id)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("group_verify_"):
        await query.answer()
        chat_id = data.split("_")[2]
        current_state = await get_verify_settings(chat_id)
        text = get_verification_text(current_state)
        reply_markup = get_group_verification_keyboard(chat_id, current_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("group_welcome_"):
        await query.answer()
        chat_id = data.split("_")[2]
        welcome_state = await get_welcome_settings(int(chat_id))
        text = get_welcome_text(welcome_state)
        reply_markup = get_welcome_keyboard(chat_id, welcome_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("group_jifen_"):
        await query.answer()
        chat_id = data.split("_")[2]
        current_state = await get_points_settings(int(chat_id))
        status_text = f'{EMOJI_SUCCESS} 开启' if current_state['status'] else f'{EMOJI_ERROR} 关闭'
        del_time = current_state.get('delete_time', 0)
        del_text = "不删除" if del_time == 0 else f"{del_time} 秒"
        text = (
            f'<tg-emoji emoji-id="5197688912457245639">🎯</tg-emoji> <b>群组积分系统</b>\n\n'
            f'启用后，用户每日签到、发言可获得独立积分。\n\n'
            f'<b>状态:</b> {status_text}\n'
            f'<b>发言积分:</b> {current_state["msg_points"]} 分/条\n'
            f'<b>过滤贴纸:</b> {"是" if current_state["ignore_stickers"] else "否"}\n'
            f'<b>签到删除:</b> {del_text}'
        )
        reply_markup = get_group_jifen_keyboard(chat_id, current_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("verify_set_"):
        parts = data.split("_")
        setting_type = parts[2]
        setting_value = parts[3]
        chat_id = parts[4]
        current_state = await get_verify_settings(chat_id)
        if setting_type == "status":
            current_state["status"] = True if setting_value == "1" else False
        elif setting_type == "mode":
            current_state["mode"] = setting_value
        elif setting_type == "dur":
            current_state["duration"] = int(setting_value)
        elif setting_type == "pen":
            current_state["penalty"] = setting_value
        await update_verify_settings(
            chat_id,
            current_state["status"],
            current_state["mode"],
            current_state["duration"],
            current_state["penalty"]
        )
        await query.answer("设置已更新！")
        text = get_verification_text(current_state)
        reply_markup = get_group_verification_keyboard(chat_id, current_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("jifen_set_"):
        parts = data.split("_")
        setting_type = parts[2]
        setting_value = parts[3]
        chat_id = int(parts[4])
        current_state = await get_points_settings(chat_id)
        if setting_type == "status":
            current_state["status"] = True if setting_value == "1" else False
        elif setting_type == "msgpts":
            current_state["msg_points"] = int(setting_value)
        elif setting_type == "sticker":
            current_state["ignore_stickers"] = True if setting_value == "1" else False
        elif setting_type == "del":
            current_state["delete_time"] = int(setting_value)
        await update_points_settings(chat_id, current_state["status"], current_state["msg_points"], current_state["ignore_stickers"], current_state.get("delete_time", 0))
        await query.answer("设置已更新！")
        status_text = f'{EMOJI_SUCCESS} 开启' if current_state['status'] else f'{EMOJI_ERROR} 关闭'
        del_time = current_state.get('delete_time', 0)
        del_text = "不删除" if del_time == 0 else f"{del_time} 秒"
        text = (
            f'<tg-emoji emoji-id="5197688912457245639">🎯</tg-emoji> <b>群组积分系统</b>\n\n'
            f'启用后，用户每日签到、发言可获得独立积分。\n\n'
            f'<b>状态:</b> {status_text}\n'
            f'<b>发言积分:</b> {current_state["msg_points"]} 分/条\n'
            f'<b>过滤贴纸:</b> {"是" if current_state["ignore_stickers"] else "否"}\n'
            f'<b>签到删除:</b> {del_text}'
        )
        reply_markup = get_group_jifen_keyboard(str(chat_id), current_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "noop":
        await query.answer()
    else:
        await query.answer()

async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_chat_member = update.my_chat_member
    if not my_chat_member:
        return
    old_status = my_chat_member.old_chat_member.status
    new_status = my_chat_member.new_chat_member.status
    chat = my_chat_member.chat
    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = config.BOT_USERNAME
    if new_status == ChatMember.ADMINISTRATOR and old_status != ChatMember.ADMINISTRATOR:
        target_panel = "group_panel"
        try:
            if chat.type == Chat.CHANNEL:
                target_panel = "pindao_panel"
                await register_channel(chat.id, chat.title, chat.username)
            elif chat.type == Chat.SUPERGROUP:
                target_panel = "group_panel"
                await register_supergroup(chat.id, chat.title, chat.username, chat.type)
            elif chat.type == Chat.GROUP:
                target_panel = "group_panel"
                text_warn = f'{EMOJI_WARN} 当前群组为普通群组，请升级为<b>超级群组 (Supergroup)</b> 以开启功能！'
                warn_msg = await context.bot.send_message(chat_id=chat.id, text=text_warn, parse_mode="HTML")
                asyncio.create_task(auto_delete_message(context.bot, chat.id, warn_msg.message_id, 300))
        except Exception as e:
            pass
        owner_id = None
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            for admin in admins:
                if admin.status == ChatMember.OWNER:
                    owner_id = admin.user.id
                    break
        except Exception as e:
            pass
        if owner_id:
            try:
                owner_text = f'<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 您的频道/群组 <b>{chat.title}</b> 已成功绑定！点击下方按钮进入私聊管理：'
                await context.bot.send_message(
                    chat_id=owner_id,
                    text=owner_text,
                    parse_mode="HTML",
                    reply_markup=get_private_chat_keyboard(bot_username, target_panel)
                )
            except Exception as e:
                pass
        try:
            text = '<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 我已升级为管理员，已向群主/频道主发送私聊管理面板通知！'
            msg = await context.bot.send_message(
                chat_id=chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_private_chat_keyboard(bot_username, target_panel)
            )
            asyncio.create_task(auto_delete_message(context.bot, chat.id, msg.message_id, 300))
        except Exception as e:
            pass
    elif new_status in [ChatMember.MEMBER, ChatMember.RESTRICTED] and old_status in [ChatMember.LEFT, ChatMember.BANNED]:
        try:
            if chat.type == Chat.GROUP:
                text_warn = f'{EMOJI_WARN} 请将我设置为管理员，并升级为超级群组以开启管理！'
                warn_msg = await context.bot.send_message(chat_id=chat.id, text=text_warn, parse_mode="HTML")
                asyncio.create_task(auto_delete_message(context.bot, chat.id, warn_msg.message_id, 300))
            else:
                text = '<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 请将我升级为管理员，以开启管理面板～'
                msg = await context.bot.send_message(chat_id=chat.id, text=text, parse_mode="HTML")
                asyncio.create_task(auto_delete_message(context.bot, chat.id, msg.message_id, 300))
        except Exception as e:
            pass

async def group_to_supergroup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.migrate_to_chat_id:
        return
    new_chat_id = message.migrate_to_chat_id
    try:
        new_chat = await context.bot.get_chat(new_chat_id)
        member = await context.bot.get_chat_member(new_chat_id, context.bot.id)
        if member.status == ChatMember.ADMINISTRATOR:
            await register_supergroup(new_chat_id, new_chat.title, new_chat.username, "supergroup")
            text = '<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 群组已升级为超级群组，独立数据库表更新完成！'
            msg = await context.bot.send_message(chat_id=new_chat_id, text=text, parse_mode="HTML")
            asyncio.create_task(auto_delete_message(context.bot, new_chat_id, msg.message_id, 300))
    except Exception as e:
        pass

def parse_time_duration(arg: str) -> int:
    arg = arg.strip().lower()
    if not arg:
        return None
    match = re.match(r'^(\d+)([mhdw])?$', arg)
    if not match:
        return None
    num = int(match.group(1))
    unit = match.group(2) or 'm'
    if unit == 'm':
        return num * 60
    elif unit == 'h':
        return num * 3600
    elif unit == 'd':
        return num * 86400
    elif unit == 'w':
        return num * 604800
    return None

async def _get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        args = context.args
        if args:
            mention = args[0]
            if mention.startswith('@'):
                username = mention[1:]
                try:
                    chat = update.effective_chat
                    members = await context.bot.get_chat_administrators(chat.id)
                    for m in members:
                        if m.user.username and m.user.username.lower() == username.lower():
                            target_user = m.user
                            break
                    if not target_user:
                        target_user = await context.bot.get_chat_member(chat.id, username)
                        target_user = target_user.user
                except Exception:
                    pass
            else:
                try:
                    user_id = int(mention)
                    target_user = await context.bot.get_chat_member(update.effective_chat.id, user_id)
                    target_user = target_user.user
                except Exception:
                    pass
    return target_user

async def _check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_html(f"{EMOJI_WARN} 此命令仅限群组使用。")
        return
    if not await _check_admin(update, context):
        await update.message.reply_html(f"{EMOJI_WARN} 只有管理员才能使用此命令。")
        return
    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_html(f"{EMOJI_WARN} 请回复目标用户或 @提及。")
        return
    duration = None
    if context.args:
        dur_arg = context.args[-1] if len(context.args) > 1 else context.args[0]
        duration = parse_time_duration(dur_arg)
    if not duration:
        duration = 60
    until_date = datetime.utcnow() + timedelta(seconds=duration)
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await log_group_action(update.effective_chat.id, target.id, f"mute_{duration}s")
        chat_id = update.effective_chat.id
        text = f"{EMOJI_SUCCESS} {target.mention_html()} 已被禁言 {duration//60} 分钟。"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("管理员解禁", callback_data=f"unmute_btn_{target.id}_{chat_id}")]
        ])
        await update.message.reply_html(text, reply_markup=keyboard)
    except Exception as e:
        await update.message.reply_html(f"{EMOJI_ERROR} 禁言失败: {e}")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    if not await _check_admin(update, context):
        await update.message.reply_html(f"{EMOJI_WARN} 只有管理员才能使用此命令。")
        return
    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_html(f"{EMOJI_WARN} 请回复目标用户或 @提及。")
        return
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
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
        await log_group_action(update.effective_chat.id, target.id, "unmute")
        await update.message.reply_html(f"{EMOJI_SUCCESS} {target.mention_html()} 已解除禁言。")
    except Exception as e:
        await update.message.reply_html(f"{EMOJI_ERROR} 解除禁言失败: {e}")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    if not await _check_admin(update, context):
        await update.message.reply_html(f"{EMOJI_WARN} 只有管理员才能使用此命令。")
        return
    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_html(f"{EMOJI_WARN} 请回复目标用户或 @提及。")
        return
    duration = None
    if context.args:
        dur_arg = context.args[-1] if len(context.args) > 1 else context.args[0]
        duration = parse_time_duration(dur_arg)
    if duration:
        until_date = datetime.utcnow() + timedelta(seconds=duration)
        await context.bot.ban_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            until_date=until_date
        )
        await log_group_action(update.effective_chat.id, target.id, f"ban_{duration}s")
        await update.message.reply_html(f"{EMOJI_SUCCESS} {target.mention_html()} 已被封禁 {duration//60} 分钟。")
    else:
        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=target.id)
        await log_group_action(update.effective_chat.id, target.id, "ban_permanent")
        await update.message.reply_html(f"{EMOJI_SUCCESS} {target.mention_html()} 已被永久封禁。")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    if not await _check_admin(update, context):
        await update.message.reply_html(f"{EMOJI_WARN} 只有管理员才能使用此命令。")
        return
    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_html(f"{EMOJI_WARN} 请回复目标用户或 @提及。")
        return
    try:
        await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=target.id)
        await log_group_action(update.effective_chat.id, target.id, "unban")
        await update.message.reply_html(f"{EMOJI_SUCCESS} {target.mention_html()} 已解除封禁。")
    except Exception as e:
        await update.message.reply_html(f"{EMOJI_ERROR} 解除封禁失败: {e}")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    if not await _check_admin(update, context):
        await update.message.reply_html(f"{EMOJI_WARN} 只有管理员才能使用此命令。")
        return
    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_html(f"{EMOJI_WARN} 请回复目标用户或 @提及。")
        return
    try:
        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=target.id)
        await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=target.id)
        await log_group_action(update.effective_chat.id, target.id, "kick")
        await update.message.reply_html(f"{EMOJI_SUCCESS} {target.mention_html()} 已被踢出。")
    except Exception as e:
        await update.message.reply_html(f"{EMOJI_ERROR} 踢出失败: {e}")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _get_target_user(update, context)
    if not target:
        target = update.effective_user
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, target.id)
        status_map = {
            'creator': '群主',
            'administrator': '管理员',
            'member': '成员',
            'restricted': '受限',
            'left': '已离开',
            'kicked': '已封禁'
        }
        status_text = status_map.get(member.status, member.status)
        tz = await get_user_timezone(target.id)
        points = await get_user_points(update.effective_chat.id, target.id)
        msg = (
            f"<b>用户信息</b>\n"
            f"ID: {target.id}\n"
            f"姓名: {target.full_name}\n"
            f"用户名: @{target.username or '无'}\n"
            f"时区: {tz}\n"
            f"积分: {points}"
        )
        await update.message.reply_html(msg)
    except Exception as e:
        await update.message.reply_html(f"{EMOJI_ERROR} 获取信息失败: {e}")

async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    if not await _check_admin(update, context):
        await update.message.reply_html(f"{EMOJI_WARN} 只有管理员才能调整积分。")
        return
    if not context.args:
        await update.message.reply_html("用法: /points [@用户] 数值  或 /points 数值 (回复用户)")
        return
    target = await _get_target_user(update, context)
    if not target:
        args = context.args
        if len(args) >= 1:
            try:
                delta = int(args[-1])
                if update.message.reply_to_message:
                    target = update.message.reply_to_message.from_user
                else:
                    target = update.effective_user
            except ValueError:
                for arg in args:
                    try:
                        delta = int(arg)
                        break
                    except ValueError:
                        pass
                else:
                    await update.message.reply_html(f"{EMOJI_ERROR} 请提供有效的积分数值。")
                    return
        else:
            await update.message.reply_html(f"{EMOJI_ERROR} 缺少积分数值。")
            return
    else:
        try:
            delta = int(context.args[-1])
        except ValueError:
            await update.message.reply_html(f"{EMOJI_ERROR} 请提供有效的积分数值。")
            return
    if delta == 0:
        await update.message.reply_html(f"{EMOJI_ERROR} 积分变化不能为0。")
        return
    new_total = await update_user_points_direct(update.effective_chat.id, target.id, delta)
    await log_group_action(update.effective_chat.id, target.id, f"points_{delta}")
    await update.message.reply_html(
        f"{EMOJI_SUCCESS} {target.mention_html()} 积分已{'增加' if delta>0 else '扣除'} {abs(delta)} 分，当前积分: {new_total}"
    )

async def points_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    chat_id = update.effective_chat.id
    limit = 10
    if context.args and context.args[0].isdigit():
        limit = int(context.args[0])
        if limit > 50:
            limit = 50
    rank = await get_points_rank(chat_id, limit)
    if not rank:
        await update.message.reply_html(f"{EMOJI_CHART} 暂无积分排名数据。")
        return
    lines = [f"{EMOJI_TROPHY} <b>积分排行榜</b>"]
    for idx, (user_id, points) in enumerate(rank, 1):
        try:
            user = await context.bot.get_chat_member(chat_id, user_id)
            name = user.user.full_name or user.user.username or str(user_id)
        except Exception:
            name = str(user_id)
        lines.append(f"{idx}. {name} — {points} 分")
    await update.message.reply_html("\n".join(lines))
    
    
    
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """<tg-emoji emoji-id="5422439311196834318">💡</tg-emoji> 群组管理命令说明

/help 打开帮助菜单


<tg-emoji emoji-id="5942877472163892475">👥</tg-emoji> 成员管理:
<tg-emoji emoji-id="5974558538213625534">🔇</tg-emoji> /mute 禁言:
-> 回复 /mute 4m  (4m = 4分钟, 3h = 3小时, 6d = 6天, 5w = 5周)
-> 回复 /mute 4  (不加单位, 默认分钟)
-> 发送 /mute @用户 4m
-> 发送 /mute @用户 4

<tg-emoji emoji-id="5240241223632954241">🚫</tg-emoji> /ban 封禁:
-> 回复 /ban 4m  (4m = 4分钟, 3h = 3小时, 6d = 6天, 5w = 5周)
-> 回复 /ban 4  (不加单位, 默认分钟)
-> 发送 /ban @用户 4m
-> 发送 /ban @用户 4

<tg-emoji emoji-id="6017024009445576290">🔓</tg-emoji> /unmute 解除禁言:
-> 回复 /unmute
-> 发送 /unmute @用户

<tg-emoji emoji-id="6017024009445576290">🆓</tg-emoji> /unban 解除封禁:
-> 回复 /unban
-> 发送 /unban @用户

<tg-emoji emoji-id="6017288111279575194">👢</tg-emoji>/kick 踢出成员:
-> 回复 /kick
-> 发送 /kick @用户

<tg-emoji emoji-id="5258503720928288433">ℹ️</tg-emoji> /info 查看用户信息:
-> 发送 /info 查看自身信息
-> 回复用户 /info 查看被回复人信息
-> 发送 /info @用户 或者 id 查看指定用户信息

<tg-emoji emoji-id="5775937998948404844">➕</tg-emoji> 积分系统:
<tg-emoji emoji-id="5775937998948404844">➕</tg-emoji> /points 10 增加10积分
<tg-emoji emoji-id="5775937998948404844">➕</tg-emoji> /points @xxx 10 @某人增加10积分
➖ /points -10 扣除10积分
<tg-emoji emoji-id="4974535910839288905">🏆</tg-emoji> /points_rank 积分排名"""
    await update.message.reply_html(text)
