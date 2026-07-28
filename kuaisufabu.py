import logging
import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
from telegram import InlineQueryResultArticle, InputTextMessageContent
import database
from lang import t

logger = logging.getLogger(__name__)
logger.info("kuaisufabu module loaded")


def _gen_keyword() -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
ADD_EMOJI_ID = "5775937998948404844"
BACK_EMOJI_ID = "5875082500023258804"
DELETE_EMOJI_ID = "6017288111279575194"
TEXT_EMOJI_ID = "5879895758202735862"
MEDIA_EMOJI_ID = "5395440575543520059"
BTN_EMOJI_ID = "5879841310902324730"
WARN_EMOJI_ID = "5447644880824181073"
SEND_EMOJI_ID = "5875506366050734240"
PREVIEW_EMOJI_ID = "5960714428394507968"

EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

from welcome import get_message_html, preprocess_button_text, parse_welcome_buttons

_AWAIT_KUAISU_INPUT = {}


async def get_kuaisu_list(creator_id: int) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, creator_id, name, keyword, content_text, buttons_text, media_type, media_file_id, status, created_at FROM group_kuaisufabu WHERE creator_id = %s ORDER BY id ASC", (creator_id,))
                rows = await cur.fetchall()
                return [{"id": r[0], "creator_id": r[1], "name": r[2], "keyword": r[3], "content_text": r[4],
                         "buttons_text": r[5], "media_type": r[6], "media_file_id": r[7], "status": bool(r[8]), "created_at": r[9]} for r in rows]
    except Exception as e:
        logger.error(f"get_kuaisu_list err: {e}", exc_info=True)
        return []


async def get_kuaisu_by_id(ks_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, creator_id, name, keyword, content_text, buttons_text, media_type, media_file_id, status, created_at FROM group_kuaisufabu WHERE id = %s", (ks_id,))
                r = await cur.fetchone()
                if r:
                    return {"id": r[0], "creator_id": r[1], "name": r[2], "keyword": r[3], "content_text": r[4],
                            "buttons_text": r[5], "media_type": r[6], "media_file_id": r[7], "status": bool(r[8]), "created_at": r[9]}
    except Exception as e:
        logger.error(f"get_kuaisu_by_id err: {e}", exc_info=True)
    return None


async def create_kuaisu(creator_id: int, name: str, keyword: str) -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO group_kuaisufabu (creator_id, name, keyword) VALUES (%s,%s,%s)", (creator_id, name, keyword))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"create_kuaisu err: {e}", exc_info=True)
        return 0


async def update_kuaisu(ks_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{k}=%s")
                    vals.append(v)
                vals.append(ks_id)
                await cur.execute(f"UPDATE group_kuaisufabu SET {', '.join(parts)} WHERE id = %s", vals)
    except Exception as e:
        logger.error(f"update_kuaisu err: {e}", exc_info=True)


async def delete_kuaisu(ks_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM group_kuaisufabu WHERE id = %s", (ks_id,))
    except Exception as e:
        logger.error(f"delete_kuaisu err: {e}", exc_info=True)


async def toggle_kuaisu_status(ks_id: int) -> bool:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM group_kuaisufabu WHERE id = %s", (ks_id,))
                r = await cur.fetchone()
                if r:
                    ns = not bool(r[0])
                    await cur.execute("UPDATE group_kuaisufabu SET status = %s WHERE id = %s", (ns, ks_id))
                    return ns
    except Exception as e:
        logger.error(f"toggle_kuaisu_status err: {e}", exc_info=True)
    return False


async def search_kuaisu_by_keyword(query: str) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, creator_id, name, keyword, content_text, buttons_text, media_type, media_file_id, status FROM group_kuaisufabu WHERE status = TRUE AND keyword LIKE %s", (f"%{query}%",))
                rows = await cur.fetchall()
                return [{"id": r[0], "creator_id": r[1], "name": r[2], "keyword": r[3], "content_text": r[4],
                         "buttons_text": r[5], "media_type": r[6], "media_file_id": r[7], "status": bool(r[8])} for r in rows]
    except Exception as e:
        logger.error(f"search_kuaisu_by_keyword err: {e}", exc_info=True)
        return []


async def get_kuaisu_list_text(items: list, user_id: int = 0) -> str:
    title = await t(user_id, "kuaisu_title") if user_id else "快捷发布"
    desc = await t(user_id, "kuaisu_desc") if user_id else "设置帖子文字、媒体、按钮等参数"
    no_data = await t(user_id, "kuaisu_no_data") if user_id else "暂无消息模板，点击下方按钮添加。"
    text = f'<tg-emoji emoji-id="{SEND_EMOJI_ID}">📝</tg-emoji> <b>{title}</b>\n{desc}\n'
    if not items:
        text += f'\n{EMOJI_WARN} {no_data}'
    else:
        for idx, item in enumerate(items, 1):
            status_icon = "✅" if item["status"] else "❌"
            has_text = f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji>' if item.get("content_text") else ""
            has_media = f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">📷</tg-emoji>' if item.get("media_file_id") else ""
            has_btn = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji>' if item.get("buttons_text") else ""
            extras = " ".join(filter(None, [has_text, has_media, has_btn]))
            text += f'\n消息{idx} 名称:{item["name"]}\n┣媒体图片: {status_icon}\n┣链接按钮: {"✅" if item.get("buttons_text") else "❌"}\n┣文本内容: {"✅" if item.get("content_text") else "❌"}\n┗内联分享: @{_bot_username} {item["keyword"]} {extras}\n'
    return text


_bot_username = ""


def set_bot_username(username: str):
    global _bot_username
    _bot_username = username


def get_kuaisu_list_keyboard(items: list) -> InlineKeyboardMarkup:
    keyboard = []
    for item in items:
        status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
        keyboard.append([
            InlineKeyboardButton(item["name"], callback_data=f"kf_detail_{item['creator_id']}_{item['id']}", icon_custom_emoji_id=SEND_EMOJI_ID),
            InlineKeyboardButton("分享", switch_inline_query=item["keyword"]),
            InlineKeyboardButton("删", callback_data=f"kf_delete_{item['creator_id']}_{item['id']}", icon_custom_emoji_id=DELETE_EMOJI_ID)
        ])
    keyboard.append([InlineKeyboardButton("添加快捷消息", callback_data="kf_create", icon_custom_emoji_id=ADD_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


def get_kuaisu_detail_text(item: dict) -> str:
    status_text = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji> 开启' if item["status"] else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji> 关闭'
    has_media = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item.get("media_file_id") else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    has_buttons = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item.get("buttons_text") else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    has_text = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>' if item.get("content_text") else f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'
    return (
        f'<tg-emoji emoji-id="{SEND_EMOJI_ID}">📝</tg-emoji> <b>快捷消息详情</b>\n\n'
        f'<b>名称:</b> {item["name"]}\n'
        f'<b>关键词:</b> {item["keyword"]}\n'
        f'<b>状态:</b> {status_text}\n'
        f'<b>文本:</b> {has_text}\n'
        f'<b>媒体:</b> {has_media}\n'
        f'<b>按钮:</b> {has_buttons}\n'
        f'\n内联用法：\n<code>@{_bot_username} {item["keyword"]}</code>'
    )


def get_kuaisu_detail_keyboard(ks_id: int, item: dict) -> InlineKeyboardMarkup:
    status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
    cid = item["creator_id"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("关闭" if item["status"] else "开启", callback_data=f"kf_toggle_{cid}_{ks_id}", icon_custom_emoji_id=CROSS_EMOJI_ID if item["status"] else CHECK_EMOJI_ID)],
        [InlineKeyboardButton("修改文本", callback_data=f"kf_edit_text_{cid}_{ks_id}", icon_custom_emoji_id=TEXT_EMOJI_ID),
         InlineKeyboardButton("修改媒体", callback_data=f"kf_edit_media_{cid}_{ks_id}", icon_custom_emoji_id=MEDIA_EMOJI_ID)],
        [InlineKeyboardButton("修改按钮", callback_data=f"kf_edit_btn_{cid}_{ks_id}", icon_custom_emoji_id=BTN_EMOJI_ID),
         InlineKeyboardButton("修改信息", callback_data=f"kf_edit_info_{cid}_{ks_id}", icon_custom_emoji_id=ADD_EMOJI_ID)],
        [InlineKeyboardButton("预览", callback_data=f"kf_preview_{cid}_{ks_id}", icon_custom_emoji_id=PREVIEW_EMOJI_ID)],
        [InlineKeyboardButton("删除", callback_data=f"kf_delete_{cid}_{ks_id}", icon_custom_emoji_id=DELETE_EMOJI_ID)],
        [InlineKeyboardButton("« 返回列表", callback_data="post_fast")]
    ])


def get_cancel_keyboard(ks_id: int = 0, cid: int = 0) -> InlineKeyboardMarkup:
    if ks_id:
        cb = f"kf_detail_{cid}_{ks_id}"
    else:
        cb = "post_fast"
    return InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=cb)]])


async def send_kuaisu_panel(context, user_id: int, target_chat_id: int):
    items = await get_kuaisu_list(user_id)
    global _bot_username
    if not _bot_username:
        try:
            me = await context.bot.get_me()
            _bot_username = me.username
        except Exception:
            pass
    text = await get_kuaisu_list_text(items, user_id)
    reply_markup = get_kuaisu_list_keyboard(items)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def kuaisufabu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    if data == "post_fast":
        await query.answer()
        global _bot_username
        if not _bot_username:
            try:
                me = await context.bot.get_me()
                _bot_username = me.username
            except Exception:
                pass
        await query.message.delete()
        await send_kuaisu_panel(context, user_id, update.effective_chat.id)
        return

    if data == "kf_create":
        await query.answer()
        _AWAIT_KUAISU_INPUT[user_id] = {"type": "create_info"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data="post_fast")]])
        await query.message.reply_html(f'<tg-emoji emoji-id="{SEND_EMOJI_ID}">📝</tg-emoji> <b>添加快捷消息</b>\n\n请发送快捷消息的名称：', reply_markup=kb)
        return

    if data.startswith("kf_detail_"):
        parts = data.split("_")
        ks_id = int(parts[-1])
        item = await get_kuaisu_by_id(ks_id)
        if not item:
            await query.answer("不存在", show_alert=True)
            return
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
        return

    if data.startswith("kf_toggle_"):
        ks_id = int(data.split("_")[-1])
        await toggle_kuaisu_status(ks_id)
        await query.answer("已切换")
        item = await get_kuaisu_by_id(ks_id)
        if item:
            await query.message.edit_text(text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
        return

    if data.startswith("kf_delete_"):
        ks_id = int(data.split("_")[-1])
        await delete_kuaisu(ks_id)
        await query.answer("已删除")
        await query.message.delete()
        await send_kuaisu_panel(context, user_id, update.effective_chat.id)
        return

    if data.startswith("kf_edit_text_"):
        parts = data.split("_")
        ks_id = int(parts[-1])
        await query.answer()
        _AWAIT_KUAISU_INPUT[user_id] = {"type": "edit_text", "ks_id": ks_id}
        kb = get_cancel_keyboard(ks_id, int(parts[3]))
        await query.message.reply_html(f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>编辑文本</b>\n\n支持 HTML 和 <b>自定义会员表情</b>\n\n请发送新的文本内容：', reply_markup=kb)
        return

    if data.startswith("kf_edit_media_"):
        parts = data.split("_")
        ks_id = int(parts[-1])
        await query.answer()
        _AWAIT_KUAISU_INPUT[user_id] = {"type": "edit_media", "ks_id": ks_id}
        kb = get_cancel_keyboard(ks_id, int(parts[3]))
        await query.message.reply_html(f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">🖼</tg-emoji> <b>编辑媒体</b>\n\n请发送图片或视频，大小不超过 <b>5MB</b>\n发送 <code>清空</code> 清除', reply_markup=kb)
        return

    if data.startswith("kf_edit_btn_"):
        parts = data.split("_")
        ks_id = int(parts[-1])
        await query.answer()
        _AWAIT_KUAISU_INPUT[user_id] = {"type": "edit_buttons", "ks_id": ks_id}
        kb = get_cancel_keyboard(ks_id, int(parts[3]))
        await query.message.reply_html(f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>编辑按钮</b>\n\n格式：<b>颜色（可选）-会员表情ID-文字-链接</b>\n用 <b>&&</b> 分隔同行\n\n示例：\n<code>红色-按钮1-https://a.com && 蓝色-按钮2-https://b.com</code>\n发送 <code>清空</code> 清除', reply_markup=kb)
        return

    if data.startswith("kf_edit_info_"):
        parts = data.split("_")
        ks_id = int(parts[-1])
        item = await get_kuaisu_by_id(ks_id)
        await query.answer()
        _AWAIT_KUAISU_INPUT[user_id] = {"type": "edit_info", "ks_id": ks_id}
        kb = get_cancel_keyboard(ks_id, int(parts[3]))
        await query.message.reply_html(f'当前名称：<code>{item["name"]}</code>\n当前关键词：<code>{item["keyword"]}</code>\n\n请发送新名称：', reply_markup=kb)
        return

    if data.startswith("kf_preview_"):
        parts = data.split("_")
        ks_id = int(parts[-1])
        item = await get_kuaisu_by_id(ks_id)
        if not item:
            await query.answer("不存在", show_alert=True)
            return
        await query.answer("正在发送预览...")
        try:
            text = item.get("content_text") or item["name"]
            markup = parse_welcome_buttons(item.get("buttons_text"))
            if item.get("media_type") == "photo" and item.get("media_file_id"):
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=item["media_file_id"], caption=text, parse_mode="HTML", reply_markup=markup)
            elif item.get("media_type") == "video" and item.get("media_file_id"):
                await context.bot.send_video(chat_id=update.effective_chat.id, video=item["media_file_id"], caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            await query.message.reply_html(f"{EMOJI_ERROR} 预览失败：{e}")
        return


async def kuaisufabu_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    await_data = _AWAIT_KUAISU_INPUT.get(user_id)
    if not await_data:
        return
    message = update.message
    if message is None:
        return
    raw = (message.text or "").strip()
    atype = await_data["type"]

    if atype == "create_info":
        name = raw
        keyword = _gen_keyword()
        new_id = await create_kuaisu(user_id, name, keyword)
        _AWAIT_KUAISU_INPUT.pop(user_id, None)
        if new_id:
            await message.reply_html(f'{EMOJI_SUCCESS} 快捷消息 <b>{name}</b> 已创建（关键词：<code>{keyword}</code>）！')
        else:
            await message.reply_html(f"{EMOJI_ERROR} 创建失败")
        await send_kuaisu_panel(context, user_id, update.effective_chat.id)
        return

    if atype == "edit_info":
        ks_id = await_data["ks_id"]
        item = await get_kuaisu_by_id(ks_id)
        new_name = raw
        new_keyword = _gen_keyword()
        await update_kuaisu(ks_id, name=new_name, keyword=new_keyword)
        _AWAIT_KUAISU_INPUT.pop(user_id, None)
        item = await get_kuaisu_by_id(ks_id)
        if item:
            await message.reply_html(f"{EMOJI_SUCCESS} 已更新（关键词：<code>{new_keyword}</code>）！")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
        return

    if atype == "edit_text":
        ks_id = await_data["ks_id"]
        new_text = get_message_html(message)
        await update_kuaisu(ks_id, content_text=new_text)
        _AWAIT_KUAISU_INPUT.pop(user_id, None)
        item = await get_kuaisu_by_id(ks_id)
        await message.reply_html(f"{EMOJI_SUCCESS} 文本已更新！")
        if item:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
        return

    if atype == "edit_media":
        ks_id = await_data["ks_id"]
        if raw in ["清空", "清除", "clear"]:
            await update_kuaisu(ks_id, media_type="", media_file_id="")
            _AWAIT_KUAISU_INPUT.pop(user_id, None)
            item = await get_kuaisu_by_id(ks_id)
            await message.reply_html(f"{EMOJI_SUCCESS} 媒体已清空！")
            if item:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
            return
        media_type, media_file_id, file_size = None, None, 0
        if message.photo:
            photo = message.photo[-1]
            file_size, media_type, media_file_id = photo.file_size or 0, "photo", photo.file_id
        elif message.video:
            video = message.video
            file_size, media_type, media_file_id = video.file_size or 0, "video", video.file_id
        else:
            item = await get_kuaisu_by_id(ks_id)
            kb = get_cancel_keyboard(ks_id, item["creator_id"] if item else 0)
            await message.reply_html(f"{EMOJI_WARN} 未识别到有效图片或视频！", reply_markup=kb)
            return
        if file_size > 5 * 1024 * 1024:
            item = await get_kuaisu_by_id(ks_id)
            kb = get_cancel_keyboard(ks_id, item["creator_id"] if item else 0)
            await message.reply_html(f"{EMOJI_WARN} 文件超过 5MB 限制！", reply_markup=kb)
            return
        await update_kuaisu(ks_id, media_type=media_type, media_file_id=media_file_id)
        _AWAIT_KUAISU_INPUT.pop(user_id, None)
        item = await get_kuaisu_by_id(ks_id)
        await message.reply_html(f"{EMOJI_SUCCESS} 媒体已更新！")
        if item:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
        return

    if atype == "edit_buttons":
        ks_id = await_data["ks_id"]
        if raw in ["清空", "清除", "clear"]:
            await update_kuaisu(ks_id, buttons_text="")
            _AWAIT_KUAISU_INPUT.pop(user_id, None)
            item = await get_kuaisu_by_id(ks_id)
            await message.reply_html(f"{EMOJI_SUCCESS} 按钮已清空！")
            if item:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
            return
        processed = preprocess_button_text(message)
        markup = parse_welcome_buttons(processed)
        if not markup:
            item = await get_kuaisu_by_id(ks_id)
            kb = get_cancel_keyboard(ks_id, item["creator_id"] if item else 0)
            await message.reply_html(f"{EMOJI_WARN} 格式错误！", reply_markup=kb)
            return
        await update_kuaisu(ks_id, buttons_text=processed)
        _AWAIT_KUAISU_INPUT.pop(user_id, None)
        item = await get_kuaisu_by_id(ks_id)
        await message.reply_html(f"{EMOJI_SUCCESS} 按钮已更新！")
        if item:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=get_kuaisu_detail_text(item), parse_mode="HTML", reply_markup=get_kuaisu_detail_keyboard(ks_id, item))
        return


async def kuaisufabu_inline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.inline_query.query.strip()
    if not query_text:
        return
    global _bot_username
    if not _bot_username:
        try:
            me = await context.bot.get_me()
            _bot_username = me.username
        except Exception:
            pass
    items = await search_kuaisu_by_keyword(query_text)
    results = []
    for item in items[:50]:
        text = item.get("content_text") or item["name"]
        markup = parse_welcome_buttons(item.get("buttons_text"))
        desc_parts = [item["keyword"]]
        if item.get("media_type") == "photo":
            desc_parts.append("📷")
        elif item.get("media_type") == "video":
            desc_parts.append("🎬")
        results.append(InlineQueryResultArticle(
            id=str(item["id"]), title=item["name"], description=" ".join(desc_parts),
            input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
            reply_markup=markup
        ))
    try:
        await update.inline_query.answer(results, cache_time=1, is_personal=True)
    except Exception as e:
        logger.error(f"inline answer err: {e}")
