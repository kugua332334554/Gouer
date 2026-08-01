import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database
from lang import t_sync, DEFAULT_LANG

logger = logging.getLogger(__name__)

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
ADD_EMOJI_ID = "5775937998948404844"
DELETE_EMOJI_ID = "6017288111279575194"
TEXT_EMOJI_ID = "5879895758202735862"
MEDIA_EMOJI_ID = "5395440575543520059"
BTN_EMOJI_ID = "5879841310902324730"
KEY_EMOJI_ID = "5816469716989912535"
PREVIEW_EMOJI_ID = "5960714428394507968"
MATCH_EMOJI_ID = "5879585266426973039"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_CHECK_TG = f'<tg-emoji emoji-id="{CHECK_EMOJI_ID}">✅</tg-emoji>'
EMOJI_CROSS_TG = f'<tg-emoji emoji-id="{CROSS_EMOJI_ID}">❌</tg-emoji>'

_AWAIT_KWR = {}  # user_id → {chat_id, reply_id, field}


def _split_keywords(keyword_str: str) -> list:
    """拆分多关键词：用 | 分隔，返回去重去空的列表"""
    if not keyword_str:
        return []
    return list(dict.fromkeys(k.strip() for k in keyword_str.split("|") if k.strip()))


def get_kwr_list_keyboard(chat_id: str, replies: list, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    keyboard = []
    for item in replies:
        status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
        kw_list = _split_keywords(item["keyword"])
        label = kw_list[0][:16] if kw_list else "(空)"
        if len(kw_list) > 1:
            label += f" +{len(kw_list)-1}"
        mode = "完全" if item["match_mode"] == "exact" else "包含"
        label = f'{label} ({mode})'
        row = [
            InlineKeyboardButton(label, callback_data=f"kwr_detail_{chat_id}_{item['id']}", icon_custom_emoji_id=KEY_EMOJI_ID),
            InlineKeyboardButton(
                t_sync(lang, "close_btn") if item["status"] else t_sync(lang, "open_btn"),
                callback_data=f"kwr_toggle_{chat_id}_{item['id']}", icon_custom_emoji_id=status_icon),
            InlineKeyboardButton(t_sync(lang, "delete_short"), callback_data=f"kwr_delete_{chat_id}_{item['id']}", icon_custom_emoji_id=DELETE_EMOJI_ID)
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("添加关键词", callback_data=f"kwr_add_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« " + t_sync(lang, "back_group_manage"), callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_kwr_detail_keyboard(chat_id: str, reply_id: int, item: dict, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
    match_label = "完全匹配" if item["match_mode"] == "exact" else "包含匹配"
    keyboard = [
        [InlineKeyboardButton(f"匹配: {match_label}", callback_data=f"kwr_chmode_{chat_id}_{reply_id}", icon_custom_emoji_id=MATCH_EMOJI_ID)],
        [InlineKeyboardButton(
            t_sync(lang, "close_btn") if item["status"] else t_sync(lang, "open_btn"),
            callback_data=f"kwr_toggle_{chat_id}_{reply_id}",
            icon_custom_emoji_id=CROSS_EMOJI_ID if item["status"] else CHECK_EMOJI_ID)],
        [InlineKeyboardButton("编辑文字", callback_data=f"kwr_edittext_{chat_id}_{reply_id}", icon_custom_emoji_id=TEXT_EMOJI_ID),
         InlineKeyboardButton("编辑媒体", callback_data=f"kwr_editmedia_{chat_id}_{reply_id}", icon_custom_emoji_id=MEDIA_EMOJI_ID)],
        [InlineKeyboardButton("编辑按钮", callback_data=f"kwr_editbtn_{chat_id}_{reply_id}", icon_custom_emoji_id=BTN_EMOJI_ID),
         InlineKeyboardButton("预览", callback_data=f"kwr_preview_{chat_id}_{reply_id}", icon_custom_emoji_id=PREVIEW_EMOJI_ID)],
        [InlineKeyboardButton(t_sync(lang, "delete_short"), callback_data=f"kwr_delete_{chat_id}_{reply_id}", icon_custom_emoji_id=DELETE_EMOJI_ID)],
        [InlineKeyboardButton("« 返回列表", callback_data=f"kwr_panel_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_kwr_list_text(chat_id: str, replies: list) -> str:
    title = "关键词回复"
    desc = "设置关键词后，有人发送包含关键词的消息，Bot 自动回复。"
    no_data = "暂无关键词，点击下方按钮添加。"
    text_parts = [f'<tg-emoji emoji-id="{KEY_EMOJI_ID}">🔑</tg-emoji> <b>{title}</b>\n{desc}\n']
    if not replies:
        text_parts.append(f'\n{EMOJI_WARN} {no_data}')
    else:
        for idx, item in enumerate(replies, 1):
            status_icon = EMOJI_CHECK_TG if item["status"] else EMOJI_CROSS_TG
            mode_label = "完全匹配" if item["match_mode"] == "exact" else "包含"
            kw_list = _split_keywords(item["keyword"])
            kw_display = " | ".join(kw_list[:3])
            if len(kw_list) > 3:
                kw_display += f" +{len(kw_list)-3}"
            has_text = f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji>' if item.get("reply_text") else ""
            has_media = f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">📷</tg-emoji>' if item.get("media_file_id") else ""
            has_btn = f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji>' if item.get("buttons_text") else ""
            extras = " ".join(filter(None, [has_text, has_media, has_btn]))
            text_parts.append(f'\n{idx}. {status_icon} <b>{kw_display}</b> ({mode_label}) {extras}')
    return "".join(text_parts)


async def get_kwr_detail_text(item: dict) -> str:
    status_icon = EMOJI_CHECK_TG if item["status"] else EMOJI_CROSS_TG
    status_label = "启用" if item["status"] else "停用"
    mode_label = "完全匹配" if item["match_mode"] == "exact" else "包含匹配"
    has_text = EMOJI_CHECK_TG if item.get("reply_text") else EMOJI_CROSS_TG
    has_media = EMOJI_CHECK_TG if item.get("media_file_id") else EMOJI_CROSS_TG
    has_buttons = EMOJI_CHECK_TG if item.get("buttons_text") else EMOJI_CROSS_TG
    kw_list = _split_keywords(item["keyword"])
    kw_display = " | ".join(kw_list)
    return (
        f'<tg-emoji emoji-id="{KEY_EMOJI_ID}">🔑</tg-emoji> <b>关键词详情</b>\n\n'
        f'<b>关键词：</b>{kw_display}\n'
        f'<b>匹配模式：</b>{mode_label}\n'
        f'<b>状态：</b>{status_icon} {status_label}\n'
        f'<b>回复文字：</b>{has_text}\n'
        f'<b>回复媒体：</b>{has_media}\n'
        f'<b>回复按钮：</b>{has_buttons}'
    )


async def send_kwr_panel(context, chat_id: int, target_chat_id: int):
    """发送关键词回复面板"""
    replies = await database.get_keyword_replies(chat_id)
    text = await get_kwr_list_text(str(chat_id), replies)
    reply_markup = get_kwr_list_keyboard(str(chat_id), replies)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def send_kwr_detail(context, chat_id: str, reply_id: int, target_chat_id: int):
    """发送关键词详情面板"""
    item = await database.get_keyword_reply(reply_id)
    if not item:
        await context.bot.send_message(chat_id=target_chat_id, text=f"{EMOJI_ERROR} 该关键词不存在或已被删除。")
        return
    text = await get_kwr_detail_text(item)
    reply_markup = get_kwr_detail_keyboard(chat_id, reply_id, item)
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)


async def send_reply_message(bot, chat_id: int, item: dict):
    """发送关键词回复消息"""
    try:
        reply_text = item.get("reply_text") or ""
        buttons_text = item.get("buttons_text")
        media_type = item.get("media_type")
        media_file_id = item.get("media_file_id")
        from welcome import parse_welcome_buttons
        reply_markup = parse_welcome_buttons(buttons_text) if buttons_text else None
        if media_type == "photo" and media_file_id:
            await bot.send_photo(chat_id=chat_id, photo=media_file_id, caption=reply_text,
                                 parse_mode="HTML", reply_markup=reply_markup)
        elif media_type == "video" and media_file_id:
            await bot.send_video(chat_id=chat_id, video=media_file_id, caption=reply_text,
                                 parse_mode="HTML", reply_markup=reply_markup)
        elif media_type == "document" and media_file_id:
            await bot.send_document(chat_id=chat_id, document=media_file_id, caption=reply_text,
                                    parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text=reply_text, parse_mode="HTML",
                                   reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.error(f"send_reply_message err: {e}")
        return False


# ── Callback Handler ──────────────────────────────────

async def kwr_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    parts = data.split("_")
    try:
        # chat_id 始终在 parts[2]
        group_chat_id = int(parts[2])
        member = await context.bot.get_chat_member(group_chat_id, user.id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能管理关键词回复。", show_alert=True)
            return
    except Exception:
        return

    # ── 主面板 ──
    if data.startswith("kwr_panel_"):
        # 用户通过“取消”返回面板，清除挂起的输入等待状态
        _AWAIT_KWR.pop(user_id, None)
        chat_id = parts[2]
        await query.answer()
        await query.message.delete()
        await send_kwr_panel(context, int(chat_id), update.effective_chat.id)
        return

    # ── 添加关键词 ──
    if data.startswith("kwr_add_"):
        chat_id = parts[2]
        await query.answer()
        _AWAIT_KWR[user_id] = {"chat_id": int(chat_id), "field": "keyword"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"kwr_panel_{chat_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{KEY_EMOJI_ID}">🔑</tg-emoji> <b>添加关键词回复</b>\n\n'
            f'请发送关键词：\n'
            f'格式：<code>关键词|匹配模式</code>\n'
            f'多个关键词用 <b>|</b> 分隔，如 <code>你好|hello|hi</code>\n'
            f'匹配模式可选：<b>包含</b>（默认，消息中含关键词即触发）或 <b>完全</b>（消息完全等于关键词才触发）\n\n'
            f'示例：\n<code>你好|包含</code> → 消息中包含"你好"就回复\n'
            f'<code>菜单|功能|help|完全</code> → 发送"菜单""功能""help"中任一，完全匹配才回复',
            reply_markup=kb
        )
        return

    # ── 关键词详情 ──
    if data.startswith("kwr_detail_"):
        # 用户从编辑状态的“取消”返回详情，清除挂起的输入等待状态
        _AWAIT_KWR.pop(user_id, None)
        chat_id = parts[2]
        reply_id = int(parts[3])
        await query.answer()
        await query.message.delete()
        await send_kwr_detail(context, chat_id, reply_id, update.effective_chat.id)
        return

    # ── 切换状态 ──
    if data.startswith("kwr_toggle_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        new_status = await database.toggle_keyword_reply(reply_id)
        await query.answer(f'{"✅ 已开启" if new_status else "❌ 已关闭"}')
        item = await database.get_keyword_reply(reply_id)
        if item:
            await query.edit_message_text(
                text=await get_kwr_detail_text(item), parse_mode="HTML",
                reply_markup=get_kwr_detail_keyboard(chat_id, reply_id, item))
        return

    # ── 切换匹配模式 ──
    if data.startswith("kwr_chmode_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        item = await database.get_keyword_reply(reply_id)
        if item:
            new_mode = "exact" if item["match_mode"] == "contains" else "contains"
            await database.update_keyword_reply(reply_id, match_mode=new_mode)
            await query.answer(f'已切换为{"完全匹配" if new_mode == "exact" else "包含匹配"}')
            item = await database.get_keyword_reply(reply_id)
            await query.edit_message_text(
                text=await get_kwr_detail_text(item), parse_mode="HTML",
                reply_markup=get_kwr_detail_keyboard(chat_id, reply_id, item))
        return

    # ── 删除 ──
    if data.startswith("kwr_delete_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        await database.delete_keyword_reply(reply_id)
        await query.answer("已删除")
        await query.message.delete()
        await send_kwr_panel(context, int(chat_id), update.effective_chat.id)
        return

    # ── 预览 ──
    if data.startswith("kwr_preview_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        item = await database.get_keyword_reply(reply_id)
        if not item:
            await query.answer("该关键词不存在", show_alert=True)
            return
        if not item.get("reply_text") and not item.get("media_file_id"):
            await query.answer("暂无内容可预览", show_alert=True)
            return
        await query.answer("正在发送预览...")
        success = await send_reply_message(context.bot, update.effective_chat.id, item)
        if not success:
            await query.message.reply_html(f'{EMOJI_WARN} 预览发送失败，请检查内容设置。')
        return

    # ── 编辑文字 ──
    if data.startswith("kwr_edittext_"):
        chat_id = int(parts[2])
        reply_id = int(parts[3])
        item = await database.get_keyword_reply(reply_id)
        current = (item.get("reply_text") or "未设置")[:200] if item else "未设置"
        await query.answer()
        _AWAIT_KWR[user_id] = {"chat_id": chat_id, "reply_id": reply_id, "field": "reply_text"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("清空文字", callback_data=f"kwr_cleartext_{chat_id}_{reply_id}", icon_custom_emoji_id=DELETE_EMOJI_ID),
                                    InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>编辑回复文字</b>\n\n'
            f'支持 HTML 和<b>自定义会员表情</b>\n\n'
            f'当前内容：\n<blockquote expandable>{current}</blockquote>\n\n请发送新的文字内容：',
            reply_markup=kb
        )
        return

    # ── 编辑媒体 ──
    if data.startswith("kwr_editmedia_"):
        chat_id = int(parts[2])
        reply_id = int(parts[3])
        await query.answer()
        _AWAIT_KWR[user_id] = {"chat_id": chat_id, "reply_id": reply_id, "field": "media"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("清空媒体", callback_data=f"kwr_clearmedia_{chat_id}_{reply_id}", icon_custom_emoji_id=DELETE_EMOJI_ID),
                                    InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">🖼</tg-emoji> <b>编辑回复媒体</b>\n\n'
            f'请发送图片、视频或文件（大小不超过 5MB）：',
            reply_markup=kb
        )
        return

    # ── 编辑按钮 ──
    if data.startswith("kwr_editbtn_"):
        chat_id = int(parts[2])
        reply_id = int(parts[3])
        await query.answer()
        _AWAIT_KWR[user_id] = {"chat_id": chat_id, "reply_id": reply_id, "field": "buttons"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("清空按钮", callback_data=f"kwr_clearbtn_{chat_id}_{reply_id}", icon_custom_emoji_id=DELETE_EMOJI_ID),
                                    InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>编辑回复按钮</b>\n\n'
            f'格式：<b>颜色（可选）-按钮文字-链接</b>\n'
            f'颜色可选：红色 / 绿色 / 蓝色（也可以只写 红 / 绿 / 蓝）\n'
            f'<b>按钮图标</b>：直接在消息里插入 Telegram 会员表情即可自动识别\n'
            f'用 <b>&&</b> 分隔同行按钮，<b>换行</b>分行\n\n'
            f'示例：\n<code>蓝色-官方频道-https://t.me/channel</code>\n'
            f'<code>红色-按钮1-https://a.com && 绿色-按钮2-https://b.com</code>',
            reply_markup=kb
        )
        return

    # ── 清空文字 ──
    if data.startswith("kwr_cleartext_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        await database.update_keyword_reply(reply_id, reply_text="")
        _AWAIT_KWR.pop(user_id, None)
        await query.answer("已清空文字")
        await query.message.delete()
        await send_kwr_detail(context, chat_id, reply_id, update.effective_chat.id)
        return

    # ── 清空媒体 ──
    if data.startswith("kwr_clearmedia_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        await database.update_keyword_reply(reply_id, media_type="", media_file_id="")
        _AWAIT_KWR.pop(user_id, None)
        await query.answer("已清空媒体")
        await query.message.delete()
        await send_kwr_detail(context, chat_id, reply_id, update.effective_chat.id)
        return

    # ── 清空按钮 ──
    if data.startswith("kwr_clearbtn_"):
        chat_id = parts[2]
        reply_id = int(parts[3])
        await database.update_keyword_reply(reply_id, buttons_text="")
        _AWAIT_KWR.pop(user_id, None)
        await query.answer("已清空按钮")
        await query.message.delete()
        await send_kwr_detail(context, chat_id, reply_id, update.effective_chat.id)
        return


# ── Input Handler ─────────────────────────────────────

async def kwr_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    info = _AWAIT_KWR.get(user_id)
    if not info:
        return
    # stay silent in groups — clear stale state, don't spam
    if update.effective_chat and update.effective_chat.type != "private":
        _AWAIT_KWR.pop(user_id, None)
        return

    msg = update.message
    if not msg:
        return

    chat_id = info["chat_id"]
    field = info["field"]

    # ── 关键词输入（支持多关键词 | 分隔）──
    if field == "keyword":
        if not msg.text:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"kwr_panel_{chat_id}")]])
            await msg.reply_html(f'{EMOJI_WARN} 请发送文本关键词。格式：<code>关键词|匹配模式</code>，多关键词用 <b>|</b> 分隔', reply_markup=kb)
            return
        raw = msg.text.strip()
        keyword = raw
        match_mode = "contains"
        if "|" in raw:
            # 最后一个 | 后面的可能是匹配模式
            parts_list = raw.rsplit("|", 1)
            last_part = parts_list[1].strip()
            if last_part in ("完全", "exact", "精确", "完全匹配", "包含", "contains", "模糊"):
                keyword = parts_list[0].strip()
                match_mode = "exact" if last_part in ("完全", "exact", "精确", "完全匹配") else "contains"
            # 否则整个字符串就是关键词（用户可能输入了含|的多关键词）
        if not keyword:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"kwr_panel_{chat_id}")]])
            await msg.reply_html(f'{EMOJI_WARN} 关键词不能为空，请重新发送！', reply_markup=kb)
            return
        reply_id = await database.add_keyword_reply(chat_id, keyword, match_mode)
        if reply_id:
            _AWAIT_KWR[user_id] = {"chat_id": chat_id, "reply_id": reply_id, "field": "reply_text"}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("跳过 » 下一步", callback_data=f"kwr_editmedia_{chat_id}_{reply_id}", icon_custom_emoji_id=MEDIA_EMOJI_ID),
                                        InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
            kw_list = _split_keywords(keyword)
            kw_display = " | ".join(kw_list)
            mode_label = "完全匹配" if match_mode == "exact" else "包含匹配"
            await msg.reply_html(
                f'{EMOJI_SUCCESS} 关键词 <b>{kw_display}</b>（{mode_label}）已创建！\n\n'
                f'<tg-emoji emoji-id="{TEXT_EMOJI_ID}">📝</tg-emoji> <b>第二步：设置回复文字</b>\n\n'
                f'支持 HTML 和<b>自定义会员表情</b>\n请发送回复的文字内容：',
                reply_markup=kb
            )
        else:
            await msg.reply_html(f'{EMOJI_ERROR} 创建失败，请重试。')
        return

    # ── 回复文字 ──
    if field == "reply_text":
        reply_id = info["reply_id"]
        if not msg.text:
            return  # silently ignore non-text while user is chatting
        from welcome import get_message_html
        new_text = get_message_html(msg)
        await database.update_keyword_reply(reply_id, reply_text=new_text)
        _AWAIT_KWR[user_id] = {"chat_id": chat_id, "reply_id": reply_id, "field": "media"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("跳过 » 完成", callback_data=f"kwr_detail_{chat_id}_{reply_id}", icon_custom_emoji_id=CHECK_EMOJI_ID),
                                    InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
        await msg.reply_html(
            f'{EMOJI_SUCCESS} 回复文字已设置！\n\n'
            f'<tg-emoji emoji-id="{MEDIA_EMOJI_ID}">🖼</tg-emoji> <b>第三步：设置回复媒体（可选）</b>\n\n'
            f'请发送图片、视频或文件（大小不超过 5MB）：',
            reply_markup=kb
        )
        return

    # ── 媒体 ──
    if field == "media":
        reply_id = info["reply_id"]
        media_type = None
        media_file_id = None
        file_size = 0
        if msg.photo:
            photo = msg.photo[-1]
            file_size = photo.file_size or 0
            media_type = "photo"
            media_file_id = photo.file_id
        elif msg.video:
            video = msg.video
            file_size = video.file_size or 0
            media_type = "video"
            media_file_id = video.file_id
        elif msg.document:
            doc = msg.document
            file_size = doc.file_size or 0
            media_type = "document"
            media_file_id = doc.file_id
        else:
            # user is just chatting — silently ignore non-media messages
            return
        if file_size > 5 * 1024 * 1024:
            await msg.reply_html(f'{EMOJI_WARN} 文件大小超过 5MB 限制！')
            return
        await database.update_keyword_reply(reply_id, media_type=media_type, media_file_id=media_file_id)
        _AWAIT_KWR[user_id] = {"chat_id": chat_id, "reply_id": reply_id, "field": "buttons"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("跳过 » 完成", callback_data=f"kwr_detail_{chat_id}_{reply_id}", icon_custom_emoji_id=CHECK_EMOJI_ID),
                                    InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
        await msg.reply_html(
            f'{EMOJI_SUCCESS} 媒体已设置！\n\n'
            f'<tg-emoji emoji-id="{BTN_EMOJI_ID}">🔘</tg-emoji> <b>第四步：设置回复按钮（可选）</b>\n\n'
            f'格式：<b>颜色（可选）-按钮文字-链接</b>\n'
            f'颜色可选：红色 / 绿色 / 蓝色（也可以只写 红 / 绿 / 蓝）\n'
            f'<b>按钮图标</b>：直接在消息里插入 Telegram 会员表情即可自动识别\n'
            f'用 <b>&&</b> 分隔同行按钮，<b>换行</b>分行\n\n'
            f'示例：\n<code>蓝色-官方频道-https://t.me/channel</code>\n'
            f'<code>红色-按钮1-https://a.com && 绿色-按钮2-https://b.com</code>',
            reply_markup=kb
        )
        return

    # ── 按钮 ──
    if field == "buttons":
        reply_id = info["reply_id"]
        if not msg.text:
            return  # silently ignore non-text while user is chatting
        from welcome import parse_welcome_buttons, preprocess_button_text
        processed = preprocess_button_text(msg)
        markup = parse_welcome_buttons(processed)
        if not markup:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"kwr_detail_{chat_id}_{reply_id}")]])
            await msg.reply_html(f'{EMOJI_WARN} 按钮格式错误，请参照示例重新输入！', reply_markup=kb)
            return
        await database.update_keyword_reply(reply_id, buttons_text=processed)
        _AWAIT_KWR.pop(user_id, None)
        await msg.reply_html(f'{EMOJI_SUCCESS} 按钮已设置！关键词回复设置完成。')
        await send_kwr_detail(context, str(chat_id), reply_id, update.effective_chat.id)
        return


# ── Message Check Handler ─────────────────────────────

async def kwr_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检测消息中的关键词并自动回复（支持多关键词）"""
    msg = update.message
    if not msg or not msg.text:
        return False
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    user = update.effective_user
    if not user or user.is_bot:
        return False

    text = msg.text.strip()
    if text.startswith("/"):
        return False

    replies = await database.get_keyword_replies(chat.id)
    if not replies:
        return False

    matched = None
    for item in replies:
        if not item["status"]:
            continue
        kw_list = _split_keywords(item["keyword"])
        if not kw_list:
            continue
        match_mode = item.get("match_mode", "contains")
        for kw in kw_list:
            if match_mode == "exact":
                if text == kw:
                    matched = item
                    break
            else:  # contains
                if kw in text:
                    matched = item
                    break
        if matched:
            break

    if not matched:
        return False

    await send_reply_message(context.bot, chat.id, matched)
    return True
