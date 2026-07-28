import asyncio
import logging
from telegram import Update, ChatMember, Chat
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
    update_verify_settings
)
from keyboards import (
    get_start_keyboard, 
    get_timezone_keyboard, 
    get_add_channel_keyboard, 
    get_add_group_keyboard,
    get_private_chat_keyboard,
    get_pagination_keyboard,
    get_group_manage_keyboard,
    get_group_verification_keyboard
)

logger = logging.getLogger(__name__)

async def auto_delete_message(bot, chat_id: int, message_id: int, delay: int = 300):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"del msg fail: {e}")

def get_verification_text(state: dict) -> str:
    status_text = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji> 开启' if state['status'] else '<tg-emoji emoji-id="5778527486270770928">❌</tg-emoji> 关闭'
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
                text_warn = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> 当前群组为普通群组，请升级为<b>超级群组 (Supergroup)</b> 以开启功能！'
                warn_msg = await context.bot.send_message(chat_id=chat.id, text=text_warn, parse_mode="HTML")
                asyncio.create_task(auto_delete_message(context.bot, chat.id, warn_msg.message_id, 300))
        except Exception as e:
            logger.error(f"register chat fail: {e}", exc_info=True)
            
        owner_id = None
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            for admin in admins:
                if admin.status == ChatMember.OWNER:
                    owner_id = admin.user.id
                    break
        except Exception as e:
            logger.error(f"get owner fail: {e}")
            
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
                logger.error(f"send owner fail: {e}")
                
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
            logger.error(f"send admin notice fail: {e}", exc_info=True)
            
    elif new_status in [ChatMember.MEMBER, ChatMember.RESTRICTED] and old_status in [ChatMember.LEFT, ChatMember.BANNED]:
        try:
            if chat.type == Chat.GROUP:
                text_warn = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> 请将我设置为管理员，并升级为超级群组以开启管理！'
                warn_msg = await context.bot.send_message(chat_id=chat.id, text=text_warn, parse_mode="HTML")
                asyncio.create_task(auto_delete_message(context.bot, chat.id, warn_msg.message_id, 300))
            else:
                text = '<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 请将我升级为管理员，以开启管理面板～'
                msg = await context.bot.send_message(chat_id=chat.id, text=text, parse_mode="HTML")
                asyncio.create_task(auto_delete_message(context.bot, chat.id, msg.message_id, 300))
        except Exception as e:
            logger.error(f"send join notice fail: {e}", exc_info=True)

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
        logger.error(f"upgrade fail: {e}", exc_info=True)
