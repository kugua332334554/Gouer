import asyncio
import base64
import html as H
import logging
import os
import re
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity, ChatMember
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import config
import database
import payment
from database import validate_column_name

logger = logging.getLogger(__name__)
logger.info("card module loaded")
try:
    from pyppeteer import launch
    logger.info("pyppeteer available")
except ImportError:
    logger.warning("pyppeteer NOT installed - card rendering will fail. Run: pip install pyppeteer && apt install chromium-browser")

SHIELD_EMOJI = "5931409969613116639"
CHECK_EMOJI = "5776375003280838798"
CROSS_EMOJI = "5778527486270770928"
ADD_EMOJI = "5775937998948404844"
BACK_EMOJI = "5875082500023258804"
DELETE_EMOJI = "6017288111279575194"
PAGE_EMOJI = "5875506366050734240"
PREV_EMOJI = "5875082500023258804"
SETTINGS_EMOJI = "5931409969613116639"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'

LABELS = {"normal": "普通用户", "business": "业务人员", "vip": "VIP 用户", "internal": "内部人员", "svip5": "SVIP5 荣誉赞助认证"}
LEVELS = {"normal": ("LV0", "普通用户"), "business": ("LV2", "业务认证"), "vip": ("LV3", "VIP 成员"), "internal": ("LV4", "内部成员"), "svip5": ("SVIP5", "荣誉赞助认证")}
THEMES = {"normal": ("#2dd4ff", "#407cff"), "business": ("#b794ff", "#6d5dfc"), "vip": ("#ffd166", "#ff8a34"), "internal": ("#4df0b4", "#14b88a"), "svip5": ("#ffe7a0", "#b7791f")}

BIO_MAX = 100
DEFAULT_BIO = "该用户很神秘，尚未设置简介。"
COOLDOWN = 20

_cool = {}
_inflight = set()
_AWAIT_CARD = {}

_TPL_DIR = os.path.dirname(os.path.abspath(__file__))
_TPL_CACHE = {}

def _load_tpl(name: str) -> str:
    if name not in _TPL_CACHE:
        path = os.path.join(_TPL_DIR, f"{name}.html")
        with open(path, "r", encoding="utf-8") as f:
            _TPL_CACHE[name] = f.read()
    return _TPL_CACHE[name]


async def get_group_card_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, enabled FROM group_card WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"chat_id": row[0], "enabled": bool(row[1])}
    except Exception:
        pass
    return {"chat_id": chat_id, "enabled": False}


async def update_group_card_settings(chat_id: int, **kwargs):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_card (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_card SET {', '.join(parts)} WHERE chat_id = %s", vals)
    except Exception as e:
        logger.error(f"update_group_card_settings err: {e}")


async def get_card_users(offset: int = 0, limit: int = 10) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id, card_type, bio FROM card_users ORDER BY user_id ASC LIMIT %s OFFSET %s", (limit, offset))
                return [{"user_id": r[0], "card_type": r[1], "bio": r[2] or ""} for r in await cur.fetchall()]
    except Exception:
        return []


async def get_card_user_count() -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM card_users")
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


async def set_card_user(user_id: int, card_type: str):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO card_users (user_id, card_type) VALUES (%s, %s) ON DUPLICATE KEY UPDATE card_type = VALUES(card_type)", (int(user_id), card_type))
    except Exception as e:
        logger.error(f"set_card_user err: {e}")


async def remove_card_user(user_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM card_users WHERE user_id = %s", (int(user_id),))
    except Exception as e:
        logger.error(f"remove_card_user err: {e}")


def get_card_keyboard(chat_id: str, settings: dict) -> InlineKeyboardMarkup:
    price_text = f"购买名片月度订阅 ({config.CARD_PRICE} {config.CARD_CURRENCY})"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(price_text, callback_data=f"card_buy_{chat_id}", icon_custom_emoji_id="6044023213250319833")],
        [InlineKeyboardButton(f'功能: {"开启" if settings["enabled"] else "关闭"}', callback_data=f"card_toggle_{chat_id}", icon_custom_emoji_id=CHECK_EMOJI if settings["enabled"] else CROSS_EMOJI)],
        [InlineKeyboardButton("用户管理", callback_data=f"card_users_{chat_id}_0", icon_custom_emoji_id=ADD_EMOJI)],
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]
    ])


def get_users_keyboard(chat_id: str, users: list, page: int, total: int) -> InlineKeyboardMarkup:
    per_page = 10
    total_pages = max(1, (total + per_page - 1) // per_page)
    kb = []
    for u in users:
        label = LABELS.get(u["card_type"], u["card_type"])
        kb.append([
            InlineKeyboardButton(f'{u["user_id"]} - {label}', callback_data=f"card_edituser_{chat_id}_{u['user_id']}", icon_custom_emoji_id=SHIELD_EMOJI),
            InlineKeyboardButton("删", callback_data=f"card_deluser_{chat_id}_{u['user_id']}", icon_custom_emoji_id=DELETE_EMOJI)
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"card_users_{chat_id}_{page - 1}", icon_custom_emoji_id=PREV_EMOJI))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if (page + 1) < total_pages:
        nav.append(InlineKeyboardButton("下一页", callback_data=f"card_users_{chat_id}_{page + 1}", icon_custom_emoji_id=PAGE_EMOJI))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("添加用户", callback_data=f"card_adduser_{chat_id}", icon_custom_emoji_id=ADD_EMOJI)])
    kb.append([InlineKeyboardButton("« 返回卡片设置", callback_data=f"card_panel_{chat_id}")])
    return InlineKeyboardMarkup(kb)


def get_level_keyboard(chat_id: str, user_id: int) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(v, callback_data=f"card_setlevel_{chat_id}_{user_id}_{k}", icon_custom_emoji_id=CHECK_EMOJI)] for k, v in LABELS.items()]
    kb.append([InlineKeyboardButton("« 返回用户列表", callback_data=f"card_users_{chat_id}_0")])
    return InlineKeyboardMarkup(kb)


async def card_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    try:
        chat_id = int(data.split("_")[2])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能设置。", show_alert=True)
            return
    except Exception as e:
        logger.error(f"card callback admin check failed: data={data}, err={e}")
        return

    if data.startswith("card_buy_"):
        logger.info(f"card_buy: chat={chat_id}, user={user_id}")
        if await database.check_subscription(chat_id, "card"):
            logger.info(f"card_buy: already subscribed, chat={chat_id}")
            await query.answer("该群名片订阅仍在有效期内。", show_alert=True)
            return
        order_no = f"CARD-{chat_id}-{int(time.time())}"
        logger.info(f"card_buy: creating order {order_no}")
        result = await payment.create_order(order_no, config.CARD_CURRENCY, config.CARD_PRICE)
        logger.info(f"card_buy: create_order ok={result.get('ok')}, error={result.get('error', 'none')}")
        if not result.get("ok"):
            await query.answer(f"创建订单失败：{result.get('error', '未知')}", show_alert=True)
            return
        await query.answer()
        pay_url = result.get("pay_url", "")
        logger.info(f"card_buy: pay_url={pay_url[:60]}...")
        await database.save_payment_order(order_no, chat_id, user_id, "card", config.CARD_PRICE, config.CARD_CURRENCY)
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{payment.EMOJI_DIAMOND}">💎</tg-emoji> <b>名片月度订阅</b>\n\n'
            f'<tg-emoji emoji-id="{payment.EMOJI_STAR}">🌟</tg-emoji> 金额：{config.CARD_PRICE} {config.CARD_CURRENCY}\n'
            f"时长：30 天\n\n"
            f"<a href='{pay_url}'>👉 点击此处支付</a>\n\n"
            f"支付后自动激活，10分钟内到账。"
        )
        asyncio.create_task(payment.poll_order(context.bot, chat_id, user_id, order_no, "card"))
        return

    if data.startswith("card_panel_"):
        await query.answer()
        settings = await get_group_card_settings(chat_id)
        sub_active = await database.check_subscription(chat_id, "card")
        sub_text = f'<tg-emoji emoji-id="5805337324967432449">👑</tg-emoji> 订阅：已激活' if sub_active else '订阅：未订阅'
        text = f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>名片系统</b>\n\n{sub_text}\n\n群内 @用户 即可生成名片卡片\n\n功能：{"✅" if settings["enabled"] else "❌"}'
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_card_keyboard(str(chat_id), settings))
        return

    if data.startswith("card_toggle_"):
        if config.CARD_PRICE != "0" and not await database.check_subscription(chat_id, "card"):
            await query.answer("⚠️ 需要购买名片订阅才能开启", show_alert=True)
            return
        settings = await get_group_card_settings(chat_id)
        await update_group_card_settings(chat_id, enabled=not settings["enabled"])
        await query.answer(f'已{"开启" if not settings["enabled"] else "关闭"}')
        await query.message.delete()
        settings = await get_group_card_settings(chat_id)
        text = f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>名片系统</b>\n\n群内 @用户 即可生成名片卡片\n\n功能：{"✅" if settings["enabled"] else "❌"}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_card_keyboard(str(chat_id), settings))
        return

    if data.startswith("card_users_"):
        page = int(data.split("_")[-1])
        await query.answer()
        await query.message.delete()
        total = await get_card_user_count()
        users = await get_card_users(offset=page * 10, limit=10)
        text = f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>用户级别管理</b>\n\n共 {total} 位用户'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_users_keyboard(str(chat_id), users, page, total))
        return

    if data.startswith("card_edituser_"):
        target_uid = int(data.split("_")[-1])
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>设置用户级别</b>\n\n用户：{target_uid}', parse_mode="HTML", reply_markup=get_level_keyboard(str(chat_id), target_uid))
        return

    if data.startswith("card_setlevel_"):
        parts = data.split("_")
        target_uid, level = int(parts[3]), parts[4]
        await set_card_user(target_uid, level)
        await query.answer(f'已设置为 {LABELS.get(level, level)}')
        await query.message.delete()
        total = await get_card_user_count()
        users = await get_card_users(offset=0, limit=10)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>用户级别管理</b>\n\n共 {total} 位用户', parse_mode="HTML", reply_markup=get_users_keyboard(str(chat_id), users, 0, total))
        return

    if data.startswith("card_adduser_"):
        await query.answer()
        _AWAIT_CARD[user_id] = {"type": "add_user", "chat_id": chat_id}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"card_users_{chat_id}_0")]])
        await query.message.reply_html(f'<tg-emoji emoji-id="{ADD_EMOJI}">➕</tg-emoji> <b>添加用户</b>\n\n请发送要添加的用户 ID（数字）：', reply_markup=kb)
        return

    if data.startswith("card_deluser_"):
        target_uid = int(data.split("_")[-1])
        await remove_card_user(target_uid)
        await query.answer("已删除")
        await query.message.delete()
        total = await get_card_user_count()
        users = await get_card_users(offset=0, limit=10)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>用户级别管理</b>\n\n共 {total} 位用户', parse_mode="HTML", reply_markup=get_users_keyboard(str(chat_id), users, 0, total))
        return


async def card_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    await_data = _AWAIT_CARD.get(user_id)
    if not await_data:
        return
    message = update.message
    if not message or not message.text:
        return
    raw = message.text.strip()
    chat_id = await_data["chat_id"]
    atype = await_data["type"]

    if atype == "add_user":
        try:
            target_uid = int(raw)
        except ValueError:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"card_users_{chat_id}_0")]])
            await message.reply_html(f"{EMOJI_WARN} 请输入有效的数字 ID。", reply_markup=kb)
            return
        _AWAIT_CARD.pop(user_id, None)
        await message.delete()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> <b>为用户 {target_uid} 选择级别</b>',
            parse_mode="HTML",
            reply_markup=get_level_keyboard(str(chat_id), target_uid)
        )
        return


async def try_card(message, bot, context):
    chat_id = message.chat_id
    settings = await get_group_card_settings(chat_id)
    if not settings["enabled"]:
        return False
    if config.CARD_PRICE != "0" and not await database.check_subscription(chat_id, "card"):
        return False
    logger.info(f"try_card: chat={chat_id}, text={str(message.text)[:50] if message.text else 'no text'}, entities={len(message.entities or [])}")
    text = message.text or message.caption
    if not text:
        return False
    ents = message.entities or message.caption_entities or []
    if len(ents) != 1:
        return False
    e = ents[0]
    if e.type == MessageEntity.TEXT_MENTION and e.user and not e.user.is_bot:
        target = e.user
    elif e.type == MessageEntity.MENTION:
        name = text[e.offset + 1:e.offset + e.length]
        if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", name):
            return False
        target = None
    else:
        return False
    uid = target.id if target else None
    key = (chat_id, uid or name)
    now = time.monotonic()
    if key in _inflight or now - _cool.get(key, 0) < COOLDOWN:
        return True
    _cool[key] = now
    # 定期清理过期冷却条目，而非全量清空（防止内存泄漏 + 避免误伤刚触发的冷却）
    if len(_cool) > 2000:
        cutoff = now - COOLDOWN
        expired = [k for k, v in _cool.items() if v < cutoff]
        for k in expired:
            _cool.pop(k, None)
        # 兜底：如果清理后仍然过多（极少情况），全量清空
        if len(_cool) > 3000:
            _cool.clear()
    _inflight.add(key)
    asyncio.create_task(_send_card(message, bot, target, name if not target else None, key))
    return True


async def _send_card(message, bot, target_user, username, key):
    uid = None
    if target_user:
        uid = target_user.id
        name = (target_user.full_name or "").strip()
        uname = target_user.username or ""
        # 自动录入 users 表，下次 @ 直接查库
        try:
            async with database.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO users (user_id, username, first_name) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE username=VALUES(username), first_name=VALUES(first_name)",
                        (uid, uname, name))
        except Exception:
            pass
    else:
        try:
            async with database.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT user_id, username, first_name FROM users WHERE username=%s LIMIT 1", (username,))
                    row = await cur.fetchone()
                    if not row:
                        await cur.execute("SELECT user_id, username, first_name FROM users WHERE LOWER(username)=%s LIMIT 1", (username.lower(),))
                        row = await cur.fetchone()
                    if row:
                        uid, uname = row[0], row[1] or username
                        name = (row[2] or "").strip()
        except Exception as e:
            logger.error(f"card: DB lookup failed for @{username}: {e}")
    if uid is None:
        logger.warning(f"card: user not found for @{username} — user hasn't /start'ed the bot yet, cannot resolve username to ID")
        return
    async with database.db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT card_type FROM card_users WHERE user_id=%s", (int(uid),))
            card_row = await cur.fetchone()
            await cur.execute("SELECT bio FROM users WHERE user_id=%s", (int(uid),))
            user_row = await cur.fetchone()
    ct = "normal" if not card_row else (card_row[0] if card_row[0] in LABELS else "normal")
    bio = (user_row[0] or "").strip() if user_row else ""
    try:
        avatar_bytes = None
        try:
            photos = await bot.get_user_profile_photos(user_id=int(uid), limit=1)
            if photos.photos:
                f = await bot.get_file(photos.photos[0][-1].file_id)
                avatar_bytes = bytes(await f.download_as_bytearray())
        except Exception:
            pass
        settings = await get_group_card_settings(message.chat_id)
        html_text = _load_tpl("normal")
        level, level_name = LEVELS[ct]
        accent, accent2 = THEMES[ct]
        tier_class = ct if ct == "svip5" else ""
        safe_name = (name or uname or "User").strip()[:40] or "User"
        ini = "".join(w[0].upper() for w in safe_name.split() if w)[:2] or "U"
        photo_html = ('<img class="avatar" src="data:image/jpeg;base64,%s" alt="">' % base64.b64encode(avatar_bytes).decode()
                      if avatar_bytes and len(avatar_bytes) > 100 else '<div class="initials">%s</div>' % H.escape(ini))
        digit = (re.sub(r"[^A-Za-z0-9]", "", str(uid)) or "0").rjust(12, "0")[-12:]
        auth_code = "-".join(digit[i:i + 4] for i in range(0, 12, 4))
        name_size = str(104 if len(safe_name) <= 8 else (82 if len(safe_name) <= 14 else 64))
        safe_bio = H.escape((bio or "").strip() or DEFAULT_BIO)
        safe_full_name = H.escape(safe_name)
        safe_uid = H.escape(str(uid))
        safe_uname = H.escape(uname or "unknown")
        html = (html_text
                .replace('{accent}', accent)
                .replace('{accent2}', accent2)
                .replace('{auth_code}', auth_code)
                .replace('{bio}', safe_bio)
                .replace('{full_name}', safe_full_name)
                .replace('{level}', level)
                .replace('{level_name}', level_name)
                .replace('{name_size}', name_size)
                .replace('{photo_html}', photo_html)
                .replace('{tier_class}', tier_class)
                .replace('{user_id}', safe_uid)
                .replace('{username}', safe_uname))
        png = await _render(html)
        if not png:
            return
        caption = f'<tg-emoji emoji-id="{SHIELD_EMOJI}">🛡</tg-emoji> {H.escape(safe_name)}\n标签：{H.escape(LABELS[ct])}\n简介：{H.escape((bio or "").strip() or DEFAULT_BIO)[:80]}'
        await message.reply_photo(photo=png, caption=caption, parse_mode=ParseMode.HTML, allow_sending_without_reply=True)
    except Exception:
        logger.exception("send card failed uid=%s", uid)
    finally:
        _inflight.discard(key)


async def _render(html):
    try:
        from pyppeteer import launch
        browser = await launch(headless=True, executablePath=os.getenv("CHROMIUM_PATH", "/usr/bin/chromium-browser"),
                               args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        page = await browser.newPage()
        await page.setViewport({"width": 2560, "height": 1440, "deviceScaleFactor": 1})
        await page.setContent(html)
        await asyncio.sleep(0.3)
        data = await page.screenshot({"type": "png"})
        await page.close()
        await browser.close()
        return data
    except Exception as e:
        logger.error(f"render err: {e}")
        return None


async def card_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.edited_message
    if not msg:
        return
    await try_card(msg, context.bot, context)

