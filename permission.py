import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)
logger.info("permission module loaded")

PERMS = {"all": "所有管理", "add_admins": "拥有添加管理员权限的管理", "creator": "仅创建者", "ban": "拥有封禁权限"}
CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
BACK_EMOJI_ID = "5875082500023258804"
SHIELD_EMOJI_ID = "5931409969613116639"
WARN_EMOJI_ID = "5447644880824181073"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'


async def get_permission_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT permissions FROM group_permission WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row and row[0]:
                    return {"permissions": row[0].split(",")}
    except Exception as e:
        logger.error(f"get_permission_settings err: {e}", exc_info=True)
    return {"permissions": ["all"]}


async def update_permission_settings(chat_id: int, permissions: list):
    val = ",".join(permissions)
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO group_permission (chat_id, permissions) VALUES (%s, %s) ON DUPLICATE KEY UPDATE permissions = VALUES(permissions)", (chat_id, val))
    except Exception as e:
        logger.error(f"update_permission_settings err: {e}", exc_info=True)


async def check_permission(chat_id: int, user_id: int, context) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status == ChatMember.OWNER:
            return True
        if member.status != ChatMember.ADMINISTRATOR:
            return False
        settings = await get_permission_settings(chat_id)
        perms = settings["permissions"]
        if "all" in perms:
            return True
        admin = member
        if "creator" in perms and admin.status != ChatMember.OWNER:
            return False
        if "add_admins" in perms and (not hasattr(admin, 'can_promote_members') or not admin.can_promote_members):
            return False
        if "ban" in perms and (not hasattr(admin, 'can_restrict_members') or not admin.can_restrict_members):
            return False
        if not perms:
            return False
        return True
    except Exception:
        return False


def get_permission_keyboard(chat_id: str, perms: list) -> InlineKeyboardMarkup:
    keyboard = []
    for k, v in PERMS.items():
        selected = k in perms
        keyboard.append([InlineKeyboardButton(
            f'{"✅" if selected else "☐"} {v}',
            callback_data=f"perm_toggle_{chat_id}_{k}",
            icon_custom_emoji_id=CHECK_EMOJI_ID if selected else CROSS_EMOJI_ID
        )])
    keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"perm_back_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


async def permission_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    if data.startswith("perm_back_"):
        chat_id = int(data.split("_")[2])
        try:
            chat = await context.bot.get_chat(chat_id)
            if chat.type in ["channel"]:
                cb = f"manage_channel_{chat_id}"
                await query.message.delete()
                from handlers import callback_handler
                fake_data = type('obj', (object,), {'data': cb})()
                query.data = cb
                await callback_handler(update, context)
                return
        except Exception:
            pass
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='<tg-emoji emoji-id="5931409969613116639">🛡</tg-emoji> <b>群组管理面板</b>\n\n请选择你要设置的功能模块：',
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("进群验证", callback_data=f"group_verify_{chat_id}")],
                [InlineKeyboardButton("进群欢迎", callback_data=f"group_welcome_{chat_id}")],
                [InlineKeyboardButton("积分管理", callback_data=f"group_jifen_{chat_id}")],
                [InlineKeyboardButton("定时消息", callback_data=f"group_dingshi_{chat_id}")],
                [InlineKeyboardButton("违禁词", callback_data=f"group_weijinci_{chat_id}")],
                [InlineKeyboardButton("夜间模式", callback_data=f"group_night_{chat_id}")],
                [InlineKeyboardButton("抽奖", callback_data=f"group_choujiang_{chat_id}")],
                [InlineKeyboardButton("« 返回群组列表", callback_data="group")]
            ])
        )
        return

    chat_id = int(data.split("_")[2])
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status != ChatMember.OWNER:
            await query.answer("⚠️ 仅群组/频道所有者可以设置权限。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("perm_panel_"):
        await query.answer()
        perms = (await get_permission_settings(chat_id))["permissions"]
        current = "、".join(PERMS.get(p, p) for p in perms)
        text = (
            f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">⚙️</tg-emoji> <b>控制权限</b>\n\n'
            f'你可以指定哪些管理员能够设置机器人\n\n'
            f'{EMOJI_WARN} 提示：如果权限未生效，请切换按钮后重新勾选\n\n'
            f'当前: {current}\n\n'
            f'至少选择一个，可以多选'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_permission_keyboard(str(chat_id), perms))
        return

    if data.startswith("perm_toggle_"):
        key = data.split("_")[-1]
        perms = (await get_permission_settings(chat_id))["permissions"]
        if key in perms:
            perms.remove(key)
        else:
            perms.append(key)
        if not perms:
            perms = ["all"]
            await query.answer("至少保留一个权限！已重置为 所有管理", show_alert=True)
        else:
            await query.answer("已切换")
        await update_permission_settings(chat_id, perms)
        current = "、".join(PERMS.get(p, p) for p in perms)
        text = (
            f'<tg-emoji emoji-id="{SHIELD_EMOJI_ID}">⚙️</tg-emoji> <b>控制权限</b>\n\n'
            f'你可以指定哪些管理员能够设置机器人\n\n'
            f'{EMOJI_WARN} 提示：如果权限未生效，请切换按钮后重新勾选\n\n'
            f'当前: {current}\n\n'
            f'至少选择一个，可以多选'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_permission_keyboard(str(chat_id), perms))
        return


async def check_manage_permission(chat_id: int, user_id: int, context) -> bool:
    return await check_permission(chat_id, user_id, context)
