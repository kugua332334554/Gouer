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
    get_channel_manage_keyboard,
    get_group_verification_keyboard,
    get_group_jifen_keyboard
)
from dingshi import get_dingshi_count
from lang import t, get_user_lang
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
    # 仅私聊
    if update.effective_chat and update.effective_chat.type != "private":
        return
    user = update.effective_user
    # 通过 get_chat 拉取完整用户信息（包括 bio）
    try:
        chat = await context.bot.get_chat(user.id)
        last_name = chat.last_name or ""
        bio = chat.bio or ""
    except Exception:
        last_name = user.last_name or ""
        bio = ""
    await save_user(user.id, user.username, user.first_name, last_name, bio)
    try:
        bot_info = await config.get_me(context.bot)
        bot_username = bot_info.username
    except Exception:
        bot_username = config.BOT_USERNAME
    args = context.args
    if args and len(args) > 0:
        param = args[0]
        if param == "group_panel":
            groups = await get_all_groups()
            my_groups = []
            for chat_id, title in groups:
                try:
                    member = await context.bot.get_chat_member(chat_id, user.id)
                    if member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                        my_groups.append((chat_id, title))
                except Exception:
                    pass
            if not my_groups:
                ulang = await get_user_lang(user.id)
                text = await t(user.id, "add_qun", BOT_USERNAME=f"@{bot_username}")
                await update.message.reply_html(text=text, reply_markup=get_add_group_keyboard(bot_username, ulang))
                return
            text = await t(user.id, "add_qun", BOT_USERNAME=f"@{bot_username}")
            reply_markup = get_pagination_keyboard(my_groups, page=1, item_type="group", bot_username=bot_username, per_page=5)
            await update.message.reply_html(text=text, reply_markup=reply_markup)
            return
        elif param == "pindao_panel":
            channels = await get_all_channels()
            my_channels = []
            for chat_id, title in channels:
                try:
                    member = await context.bot.get_chat_member(chat_id, user.id)
                    if member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                        my_channels.append((chat_id, title))
                except Exception:
                    pass
            if not my_channels:
                ulang = await get_user_lang(user.id)
                text = await t(user.id, "add_pindao", BOT_USERNAME=f"@{bot_username}")
                await update.message.reply_html(text=text, reply_markup=get_add_channel_keyboard(bot_username, ulang))
                return
            text = await t(user.id, "add_pindao", BOT_USERNAME=f"@{bot_username}")
            reply_markup = get_pagination_keyboard(my_channels, page=1, item_type="channel", bot_username=bot_username, per_page=5)
            await update.message.reply_html(text=text, reply_markup=reply_markup)
            return
    ulang = await get_user_lang(user.id)
    text = await t(user.id, "start_message", USER=user.mention_html(), BOT_USERNAME=f"@{bot_username}")
    await update.message.reply_html(text=text, reply_markup=get_start_keyboard(ulang))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data
    try:
        bot_info = await config.get_me(context.bot)
        bot_username = bot_info.username
    except Exception:
        bot_username = config.BOT_USERNAME

    if data.startswith("unmute_btn_"):
        parts = data.split("_")
        target_id = int(parts[2])
        chat_id = int(parts[3])
        if not await _check_admin(update, context):
            await query.answer(f"⚠️ 只有管理员才能执行此操作。", show_alert=True)
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
            await query.answer(f"✅ 已解除禁言。", show_alert=True)
            await query.edit_message_text(
                text=f"{EMOJI_SUCCESS} 用户已由管理员 {user.mention_html()} 手动解禁。",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.answer(f"❌ 解禁失败: {e}", show_alert=True)
        return

    if data == "channel":
        await query.answer()
        channels = await get_all_channels()
        my_channels = []
        for chat_id, title in channels:
            try:
                member = await context.bot.get_chat_member(chat_id, user.id)
                if member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                    my_channels.append((chat_id, title))
            except Exception:
                pass
        if not my_channels:
            ulang = await get_user_lang(user_id)
            text = await t(user_id, "add_pindao", BOT_USERNAME=f"@{bot_username}")
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_add_channel_keyboard(bot_username, ulang))
            return
        text = await t(user.id, "add_pindao", BOT_USERNAME=f"@{bot_username}")
        reply_markup = get_pagination_keyboard(my_channels, page=1, item_type="channel", bot_username=bot_username, per_page=5)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "group":
        await query.answer()
        groups = await get_all_groups()
        my_groups = []
        for chat_id, title in groups:
            try:
                member = await context.bot.get_chat_member(chat_id, user.id)
                if member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                    my_groups.append((chat_id, title))
            except Exception:
                pass
        if not my_groups:
            ulang = await get_user_lang(user_id)
            text = await t(user_id, "add_qun", BOT_USERNAME=f"@{bot_username}")
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_add_group_keyboard(bot_username, ulang))
            return
        text = await t(user.id, "add_qun", BOT_USERNAME=f"@{bot_username}")
        reply_markup = get_pagination_keyboard(my_groups, page=1, item_type="group", bot_username=bot_username, per_page=5)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("page_"):
        await query.answer()
        _, item_type, page_str = data.split("_")
        page = int(page_str)
        if item_type == "group":
            items = await get_all_groups()
            text = await t(user.id, "add_qun", BOT_USERNAME=f"@{bot_username}")
        else:
            items = await get_all_channels()
            text = await t(user.id, "add_pindao", BOT_USERNAME=f"@{bot_username}")
        reply_markup = get_pagination_keyboard(items, page=page, item_type=item_type, bot_username=bot_username, per_page=5)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "timezone":
        await query.answer()
        current_tz = await get_user_timezone(user_id)
        text = await t(user_id, "timezone_message", TIMEZONE=current_tz)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_timezone_keyboard())

    elif data.startswith("tz_"):
        new_tz = data.replace("tz_", "")
        await update_user_timezone(user_id, new_tz)
        await query.answer(f"时区已更新为: {new_tz}", show_alert=True)
        text = await t(user_id, "timezone_message", TIMEZONE=new_tz)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_timezone_keyboard())

    elif data == "changelang":
        await query.answer()
        from lang import LANG_NAMES, set_user_lang, t as lang_t
        keyboard = [
            [InlineKeyboardButton(f'{v}', callback_data=f"setlang_{k}", icon_custom_emoji_id="5879585266426973039")] for k, v in LANG_NAMES.items()
        ]
        keyboard.append([InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")])
        current_lang = LANG_NAMES.get(await (__import__('lang').get_user_lang(user_id)), "简体中文")
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="5879585266426973039">🌐</tg-emoji> <b>选择语言 / Select Language</b>\n\n当前：{current_lang}',
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("setlang_"):
        lang_code = data.replace("setlang_", "")
        from lang import set_user_lang, LANG_NAMES, t as lang_t
        await set_user_lang(user_id, lang_code)
        new_name = LANG_NAMES.get(lang_code, lang_code)
        await query.answer(LANG_NAMES.get(lang_code, lang_code), show_alert=True)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="5879585266426973039">🌐</tg-emoji> 语言已切换为 {new_name}',
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")]])
        )

    elif data == "clone" or data.startswith("clone_"):
        import os as _os
        if _os.getenv("BOT_IS_CHILD") == "1":
            await query.answer()
            await query.edit_message_text(
                text=f"{EMOJI_WARN} <b>下级 Bot 不支持克隆和高级版功能。</b>",
                parse_mode="HTML"
            )
            return
        from clone import clone_callback_handler
        await clone_callback_handler(update, context)
        return

    elif data == "pro":
        import os as _os
        if _os.getenv("BOT_IS_CHILD") == "1":
            await query.answer()
            await query.edit_message_text(
                text=f"{EMOJI_WARN} <b>下级 Bot 不支持克隆和高级版功能。</b>",
                parse_mode="HTML"
            )
            return
        await query.answer()
        from payment import EMOJI_DIAMOND, EMOJI_CROWN
        text = (
            f'<tg-emoji emoji-id="{EMOJI_DIAMOND}">💎</tg-emoji> <b>高级版</b>\n\n'
            f'AI 群聊和名片功能需按月订阅。\n\n'
            f'点击下方按钮，选择要管理的群组，\n'
            f'在 AI / 名片设置面板中购买订阅。'
        )
        from keyboards import get_pro_keyboard
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_pro_keyboard(user_id))

    elif data == "back_to_main":
        await query.answer()
        ulang = await get_user_lang(user_id)
        text = await t(user_id, "start_message", USER=user.mention_html(), BOT_USERNAME=f"@{bot_username}")
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_start_keyboard(ulang))

    elif data.startswith("manage_group_"):
        await query.answer()
        chat_id = data.split("_")[2]
        try:
            member = await context.bot.get_chat_member(int(chat_id), user.id)
            if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                await query.answer("⚠️ 你不是该群组的管理员！", show_alert=True)
                return
        except Exception:
            await query.answer("⚠️ 无法验证权限", show_alert=True)
            return
        title = await t(user_id, "group_manage_panel")
        text = f'<tg-emoji emoji-id="5931409969613116639">🛡</tg-emoji> <b>{title}</b>\n\n{await t(user_id, "main_menu")}'
        reply_markup = get_group_manage_keyboard(chat_id)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("manage_channel_"):
        await query.answer()
        chat_id = data.split("_")[2]
        try:
            member = await context.bot.get_chat_member(int(chat_id), user.id)
            if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                await query.answer("⚠️ 你不是该频道的管理员！", show_alert=True)
                return
        except Exception:
            await query.answer("⚠️ 无法验证权限", show_alert=True)
            return
        try:
            chat = await context.bot.get_chat(int(chat_id))
            title = chat.title
        except Exception:
            title = "未知频道"
        dingshi_cnt = await get_dingshi_count(int(chat_id))
        try:
            from autobutton import get_autobutton_settings
            ab = await get_autobutton_settings(int(chat_id))
            ab_status = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>' if ab["status"] else '<tg-emoji emoji-id="5778527486270770928">❌</tg-emoji>'
        except Exception:
            ab_status = '<tg-emoji emoji-id="5778527486270770928">❌</tg-emoji>'
        text = (
            f'<tg-emoji emoji-id="5771695636411847302">📢</tg-emoji> <b>{title}</b>\n\n'
            f'ID: {chat_id}\n'
            f'<tg-emoji emoji-id="5258419835922030550">⏰</tg-emoji> 定时消息: {dingshi_cnt}\n'
            f'<tg-emoji emoji-id="5960714428394507968">🔄</tg-emoji> 频道同步: {ab_status}\n'
        )
        reply_markup = get_channel_manage_keyboard(chat_id)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("group_verify_"):
        await query.answer()
        chat_id = int(data.split("_")[2])
        current_state = await get_verify_settings(chat_id)
        text = get_verification_text(current_state)
        reply_markup = get_group_verification_keyboard(str(chat_id), current_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("group_welcome_"):
        await query.answer()
        chat_id = int(data.split("_")[2])
        welcome_state = await get_welcome_settings(int(chat_id))
        text = get_welcome_text(welcome_state)
        reply_markup = get_welcome_keyboard(chat_id, welcome_state)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("group_jifen_"):
        await query.answer()
        chat_id = int(data.split("_")[2])
        current_state = await get_points_settings(chat_id)
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
        chat_id = int(parts[4])
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
        bot_info = await config.get_me(context.bot)
        bot_username = bot_info.username
    except Exception:
        bot_username = config.BOT_USERNAME
    if new_status == ChatMember.ADMINISTRATOR and old_status != ChatMember.ADMINISTRATOR:
        target_panel = "group_panel"
        chat_title = chat.title or "未命名"
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
        owner_text = f'<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 您的{ "频道" if chat.type == Chat.CHANNEL else "群组" } <b>{chat_title}</b> 已成功绑定！点击下方按钮进入私聊管理：'
        kb = get_private_chat_keyboard(bot_username, target_panel)
        sent_to_owner = False
        if owner_id:
            try:
                await context.bot.send_message(chat_id=owner_id, text=owner_text, parse_mode="HTML", reply_markup=kb)
                sent_to_owner = True
            except Exception:
                pass
        try:
            if sent_to_owner:
                pub_text = f'<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 已向频道主发送私聊管理面板通知！'
            else:
                pub_text = f'<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 无法私聊频道主，请点击下方按钮进入私聊管理（需要先 @{bot_username} 私聊发送 /start）'
            msg = await context.bot.send_message(chat_id=chat.id, text=pub_text, parse_mode="HTML", reply_markup=kb)
            asyncio.create_task(auto_delete_message(context.bot, chat.id, msg.message_id, 300))
        except Exception:
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
    old_chat_id = message.chat_id
    new_chat_id = message.migrate_to_chat_id
    try:
        new_chat = await context.bot.get_chat(new_chat_id)
        member = await context.bot.get_chat_member(new_chat_id, context.bot.id)
        if member.status == ChatMember.ADMINISTRATOR:
            await register_supergroup(new_chat_id, new_chat.title, new_chat.username, "supergroup")
            # 迁移旧群配置到新 chat_id（群升级后 chat_id 改变）
            await _migrate_group_settings(old_chat_id, new_chat_id)
            text = '<tg-emoji emoji-id="6323440286445867472">⭐️</tg-emoji> 群组已升级为超级群组，历史配置已迁移！'
            msg = await context.bot.send_message(chat_id=new_chat_id, text=text, parse_mode="HTML")
            asyncio.create_task(auto_delete_message(context.bot, new_chat_id, msg.message_id, 300))
    except Exception as e:
        pass


async def _migrate_group_settings(old_chat_id: int, new_chat_id: int):
    """群组升级为超级群后，将旧 chat_id 的配置迁移到新 chat_id。"""
    import database as db
    tables_to_migrate = [
        # (table_name, id_column, is_single_row)
        ("group_settings", "chat_id", True),
        ("group_welcome", "chat_id", True),
        ("group_points_settings", "chat_id", True),
        ("group_night", "chat_id", True),
        ("group_ai", "chat_id", True),
        ("group_card", "chat_id", True),
        ("group_autodelete", "chat_id", True),
        ("group_permission", "chat_id", True),
        ("group_antispam", "chat_id", True),
        ("group_toggle", "chat_id", True),
        ("group_message_check", "chat_id", True),
        ("group_choujiang_settings", "chat_id", True),
    ]
    try:
        from database import _validate_table_name as _vtn
        async with db.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                for table, id_col, _ in tables_to_migrate:
                    _vtn(table)  # 安全校验表名
                    # 获取旧配置
                    await cur.execute(f"SELECT * FROM `{_vtn(table)}` WHERE `{id_col}` = %s", (old_chat_id,))
                    old_row = await cur.fetchone()
                    if not old_row:
                        continue
                    # 获取列名
                    await cur.execute(f"DESCRIBE `{table}`")
                    columns = [r[0] for r in await cur.fetchall()]
                    # 替换 chat_id 为新的
                    new_row = list(old_row)
                    try:
                        idx = columns.index(id_col)
                        new_row[idx] = new_chat_id
                    except ValueError:
                        pass
                    placeholders = ", ".join(["%s"] * len(new_row))
                    cols = ", ".join(f"`{c}`" for c in columns)
                    await cur.execute(
                        f"INSERT INTO `{table}` ({cols}) VALUES ({placeholders}) "
                        f"ON DUPLICATE KEY UPDATE " +
                        ", ".join(f"`{c}`=VALUES(`{c}`)" for c in columns if c != id_col),
                        new_row)
                # 迁移多行表：违禁词、定时消息、抽奖
                for table, id_col in [("group_weijinci", "chat_id"),
                                       ("group_dingshi", "chat_id"),
                                       ("group_choujiang", "chat_id"),
                                       ("group_kuaisufabu", "creator_id")]:
                    await cur.execute(f"UPDATE `{_vtn(table)}` SET `{id_col}` = %s WHERE `{id_col}` = %s",
                                      (new_chat_id, old_chat_id))
                logger.info(f"migrated group settings from {old_chat_id} to {new_chat_id}")
    except Exception as e:
        logger.error(f"migrate_group_settings err: {e}")

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

    # 1) 回复消息 → 取被回复者
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        if target_user:
            return target_user

    # 2) 从消息 entities 提取 text_mention（携带完整 user 对象）
    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user

    # 3) 从参数中解析
    args = context.args
    if not args:
        return None
    mention = args[0]
    chat = update.effective_chat

    if mention.startswith('@'):
        username = mention[1:]
        # 查数据库 users 表
        from database import get_user_id_by_username
        user_id = await get_user_id_by_username(username)
        if user_id:
            try:
                member = await context.bot.get_chat_member(chat.id, user_id)
                return member.user
            except Exception:
                pass
    else:
        try:
            user_id = int(mention)
            member = await context.bot.get_chat_member(chat.id, user_id)
            return member.user
        except Exception:
            pass

    return None

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
        await update.message.reply_html(f"{EMOJI_WARN} 找不到该用户。请回复他的消息、@他（需在群里发过言），或直接发用户ID。")
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
        await update.message.reply_html(f"{EMOJI_WARN} 找不到该用户。请回复他的消息、@他（需在群里发过言），或直接发用户ID。")
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
        await update.message.reply_html(f"{EMOJI_WARN} 找不到该用户。请回复他的消息、@他（需在群里发过言），或直接发用户ID。")
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
        await update.message.reply_html(f"{EMOJI_WARN} 找不到该用户。请回复他的消息、@他（需在群里发过言），或直接发用户ID。")
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
        await update.message.reply_html(f"{EMOJI_WARN} 找不到该用户。请回复他的消息、@他（需在群里发过言），或直接发用户ID。")
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
