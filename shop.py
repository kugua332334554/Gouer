import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database
from lang import t_sync, DEFAULT_LANG

logger = logging.getLogger(__name__)

SHOP_EMOJI = "6044023213250319833"
ADD_EMOJI_ID = "5775937998948404844"
DELETE_EMOJI_ID = "6017288111279575194"
CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
COIN_EMOJI_ID = "5208801655004350721"
COIN_EMOJI = f'<tg-emoji emoji-id="{COIN_EMOJI_ID}">🌟</tg-emoji>'
CARD_EMOJI_ID = "6059834826112901364"
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'

_AWAIT_SHOP = {}  # user_id → {chat_id, item_id, step, name, price, stock, desc, mode}


# ── Admin keyboard ────────────────────────────────────
def get_shop_admin_keyboard(chat_id: str, items: list) -> InlineKeyboardMarkup:
    keyboard = []
    for item in items:
        status_icon = CHECK_EMOJI_ID if item["status"] else CROSS_EMOJI_ID
        mode_label = "自动" if item.get("delivery_mode") == "auto" else "手动"
        stock_text = f"库存:{item['stock']}" if item["stock"] >= 0 else "无限"
        label = f'{item["name"]} ({item["points_price"]}分 {mode_label} {stock_text})'
        row = [
            InlineKeyboardButton(label, callback_data=f"shop_edit_{chat_id}_{item['id']}", icon_custom_emoji_id=SHOP_EMOJI),
            InlineKeyboardButton("删", callback_data=f"shop_del_{chat_id}_{item['id']}", icon_custom_emoji_id=DELETE_EMOJI_ID)
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("添加商品", callback_data=f"shop_add_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


# ── User shop keyboard ────────────────────────────────
def get_shop_list_keyboard(chat_id: str, items: list) -> InlineKeyboardMarkup:
    keyboard = []
    for item in items:
        if not item["status"]: continue
        mode_label = "自动发卡" if item.get("delivery_mode") == "auto" else "手动发货"
        stock_text = f"库存:{item['stock']}" if item["stock"] >= 0 else "无限"
        label = f'{item["name"]} — {item["points_price"]}分 [{mode_label}]'
        keyboard.append([InlineKeyboardButton(label, callback_data=f"shop_buy_{chat_id}_{item['id']}", icon_custom_emoji_id=SHOP_EMOJI)])
    keyboard.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


# ── Callback handler ──────────────────────────────────
async def shop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data
    parts = data.split("_")

    # ── Admin panel ──
    if data.startswith("shop_admin_"):
        chat_id = int(parts[2])
        if not await _check_admin(context, chat_id, user_id):
            await query.answer("⚠️ 只有管理员才能管理商城。", show_alert=True); return
        await query.answer()
        items = await database.get_shop_items(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城管理</b>',
            parse_mode="HTML", reply_markup=get_shop_admin_keyboard(str(chat_id), items))
        return

    # ── Step 1: ask for name ──
    if data.startswith("shop_add_"):
        chat_id = int(parts[2])
        await query.answer()
        _AWAIT_SHOP[user_id] = {"chat_id": chat_id, "step": "name"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>添加商品 — 第一步</b>\n\n请发送<b>商品名称</b>：', reply_markup=kb)
        return

    # ── Delete ──
    if data.startswith("shop_del_"):
        chat_id = int(parts[2]); item_id = int(parts[3])
        await database.delete_shop_item(item_id)
        await query.answer("已删除")
        items = await database.get_shop_items(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城管理</b>',
            parse_mode="HTML", reply_markup=get_shop_admin_keyboard(str(chat_id), items))
        return

    # ── Toggle status ──
    if data.startswith("shop_edit_"):
        chat_id = int(parts[2]); item_id = int(parts[3])
        items = await database.get_shop_items(chat_id)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item: await query.answer("商品不存在"); return
        await database.update_shop_item(item_id, status=not item["status"])
        await query.answer(f'已{"上架" if not item["status"] else "下架"}')
        items = await database.get_shop_items(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城管理</b>',
            parse_mode="HTML", reply_markup=get_shop_admin_keyboard(str(chat_id), items))
        return

    # ── User: buy confirm ──
    if data.startswith("shop_buy_"):
        chat_id = int(parts[2]); item_id = int(parts[3])
        items = await database.get_shop_items(chat_id)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item or not item["status"]:
            await query.answer("该商品已下架", show_alert=True); return
        pts = await database.get_user_points(chat_id, user_id)
        if pts < item["points_price"]:
            await query.answer(f'积分不足！需要 {item["points_price"]} 分，当前 {pts} 分', show_alert=True); return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("确认购买", callback_data=f"shop_confirm_{chat_id}_{item_id}", icon_custom_emoji_id=CHECK_EMOJI_ID),
             InlineKeyboardButton("取消", callback_data=f"shop_list_{chat_id}")]
        ])
        await query.answer()
        await query.message.reply_html(
            f'{COIN_EMOJI} <b>确认购买</b>\n\n商品：<b>{item["name"]}</b>\n价格：<b>{item["points_price"]}</b> 分\n'
            f'当前积分：{pts} 分\n\n确认购买？', reply_markup=kb)
        return

    # ── User: confirm purchase + deliver ──
    if data.startswith("shop_confirm_"):
        chat_id = int(parts[2]); item_id = int(parts[3])
        items = await database.get_shop_items(chat_id)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item or not item["status"]:
            await query.answer("商品不存在或已下架", show_alert=True); return
        pts = await database.get_user_points(chat_id, user_id)
        if pts < item["points_price"]:
            await query.answer("积分不足", show_alert=True); return

        buyer_name = user.username or user.first_name or str(user_id)
        await database.update_user_points_direct(chat_id, user_id, -item["points_price"])

        # handle delivery
        if item.get("delivery_mode") == "auto":
            # auto: pop a card code and DM it
            card = await database.pop_shop_card(item_id)
            if not card:
                await query.answer("该商品卡密已售罄！请等待补货", show_alert=True)
                # refund points
                await database.update_user_points_direct(chat_id, user_id, item["points_price"])
                return
            await query.answer("购买成功！卡密已私信发送")
        else:
            # manual: stock deduction handled by update_shop_item
            if item["stock"] > 0:
                await database.update_shop_item(item_id, stock=item["stock"] - 1)
                if item["stock"] - 1 <= 0:
                    await database.update_shop_item(item_id, status=False)
            await query.answer("购买成功！请联系管理员领取")

        await database.log_group_action(chat_id, user_id, f"shop_buy_{item_id}")

        # notify buyer via DM
        try:
            dm = f'{EMOJI_SUCCESS} <b>购买成功！</b>\n\n商品：{item["name"]}\n消费：{item["points_price"]} 分\n剩余积分：{pts - item["points_price"]}'
            if item.get("delivery_mode") == "auto" and card:
                dm += f'\n\n<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔑</tg-emoji> <b>卡密：</b>\n<code>{card}</code>'
            await context.bot.send_message(chat_id=user_id, text=dm, parse_mode="HTML")
        except Exception:
            pass

        # notify group owner via DM
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            owner = next((a.user for a in admins if a.status == "creator"), None)
            if owner and owner.id != user_id:
                await context.bot.send_message(chat_id=owner.id, text=
                    f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>商城新订单</b>\n\n'
                    f'商品：{item["name"]}\n买家：{buyer_name}\n金额：{item["points_price"]} 分',
                    parse_mode="HTML")
        except Exception:
            pass

        await query.edit_message_text(
            text=f'{EMOJI_SUCCESS} <b>购买成功！</b>\n\n商品：{item["name"]}\n消费：{item["points_price"]} 分\n剩余积分：{pts - item["points_price"]}',
            parse_mode="HTML")
        return

    # ── User: list shop ──
    if data.startswith("shop_list_"):
        chat_id = int(parts[2])
        await query.answer()
        items = await database.get_shop_items(chat_id)
        active = [i for i in items if i["status"]]
        if not active:
            await query.edit_message_text(
                text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城</b>\n\n暂无商品上架。',
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]]))
            return
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城</b>\n\n使用积分兑换商品：',
            parse_mode="HTML", reply_markup=get_shop_list_keyboard(str(chat_id), active))
        return

    # ── skip description → mode ──
    if data.startswith("shop_skipdesc_"):
        chat_id = int(data.split("_")[2])
        info = _AWAIT_SHOP.get(user_id)
        if not info: await query.answer("会话已过期"); return
        info["desc"] = ""; info["step"] = "mode"
        await query.answer(); await query.message.delete()
        mode_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("手动发货", callback_data=f"shop_setmode_{chat_id}_manual", icon_custom_emoji_id=CHECK_EMOJI_ID),
             InlineKeyboardButton("自动发卡", callback_data=f"shop_setmode_{chat_id}_auto", icon_custom_emoji_id=CARD_EMOJI_ID)],
            [InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]
        ])
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>第四步：选择发货方式</b>\n\n<b>手动发货</b>：用户购买后联系管理员领取\n<b>自动发卡</b>：用户购买后自动私信发送卡密',
            parse_mode="HTML", reply_markup=mode_kb)
        return

    # ── manual mode → ask stock ──
    if data.startswith("shop_setmode_") and "_manual" in data:
        chat_id = int(data.split("_")[2])
        info = _AWAIT_SHOP.get(user_id)
        if not info: await query.answer("会话已过期"); return
        info["step"] = "stock"; info["mode"] = "manual"
        await query.answer(); await query.message.delete()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]])
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>第五步：设置库存</b>\n\n请发送库存数量（<b>-1</b> 表示无限库存）：',
            parse_mode="HTML", reply_markup=kb)
        return

    # ── auto mode → ask cards ──
    if data.startswith("shop_setmode_") and "_auto" in data:
        chat_id = int(data.split("_")[2])
        info = _AWAIT_SHOP.get(user_id)
        if not info: await query.answer("会话已过期"); return
        info["step"] = "card"; info["mode"] = "auto"
        await query.answer(); await query.message.delete()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]])
        await context.bot.send_message(chat_id=update.effective_chat.id,
            text=f'<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔏</tg-emoji> <b>第五步：上传卡密</b>\n\n请发送卡密，<b>一行一个</b>：\n\n示例：\n<code>ABC123\nDEF456\nGHI789</code>',
            parse_mode="HTML", reply_markup=kb)
        return


# ── Input handler (step-by-step creation) ─────────────
async def shop_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    info = _AWAIT_SHOP.get(user_id)
    if not info: return
    # stay silent in groups — clear stale state, don't spam
    if update.effective_chat and update.effective_chat.type != "private":
        _AWAIT_SHOP.pop(user_id, None)
        return
    msg = update.message
    if not msg or not msg.text: return

    chat_id = info["chat_id"]
    step = info["step"]
    raw = msg.text.strip()
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]])

    # ── Step 1: name ──
    if step == "name":
        if not raw or len(raw) > 100:
            await msg.reply_html(f'{EMOJI_WARN} 名称不能为空且不超过100字，请重新发送：', reply_markup=cancel_kb); return
        info["name"] = raw; info["step"] = "price"
        await msg.reply_html(f'{EMOJI_SUCCESS} 名称：<b>{raw}</b>\n\n<tg-emoji emoji-id="{COIN_EMOJI_ID}">🌟</tg-emoji> <b>第二步：设置积分价格</b>\n\n请发送商品价格（积分数量）：', reply_markup=cancel_kb)
        return

    # ── Step 2: price ──
    if step == "price":
        try: price = int(raw)
        except ValueError:
            await msg.reply_html(f'{EMOJI_WARN} 价格必须是数字，请重新发送：', reply_markup=cancel_kb); return
        if price <= 0:
            await msg.reply_html(f'{EMOJI_WARN} 价格必须大于0，请重新发送：', reply_markup=cancel_kb); return
        info["price"] = price; info["step"] = "desc"
        skip_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("跳过 » 下一步", callback_data=f"shop_skipdesc_{chat_id}", icon_custom_emoji_id=CHECK_EMOJI_ID),
             InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]])
        await msg.reply_html(f'{EMOJI_SUCCESS} 价格：<b>{price}</b> 分\n\n<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>第三步：设置描述（可选）</b>\n\n请发送商品描述文字，或点击「跳过」：', reply_markup=skip_kb)
        return

    # ── Step 3: description ──
    if step == "desc":
        info["desc"] = raw; info["step"] = "mode"
        mode_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("手动发货", callback_data=f"shop_setmode_{chat_id}_manual", icon_custom_emoji_id=CHECK_EMOJI_ID),
             InlineKeyboardButton("自动发卡", callback_data=f"shop_setmode_{chat_id}_auto", icon_custom_emoji_id=CARD_EMOJI_ID)],
            [InlineKeyboardButton("« 取消", callback_data=f"shop_admin_{chat_id}")]
        ])
        await msg.reply_html(f'{EMOJI_SUCCESS} 描述已保存\n\n<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>第四步：选择发货方式</b>\n\n<b>手动发货</b>：用户购买后联系管理员领取\n<b>自动发卡</b>：用户购买后自动私信发送卡密', reply_markup=mode_kb)
        return

    # ── step: stock (manual mode only) ──
    if step == "stock":
        try: stock = int(raw)
        except ValueError:
            await msg.reply_html(f'{EMOJI_WARN} 库存必须是数字，请重新发送：', reply_markup=cancel_kb); return
        name = info.get("name", ""); price = info.get("price", 0)
        desc = info.get("desc", "")
        item_id = await database.add_shop_item(chat_id, name, price, stock, desc)
        _AWAIT_SHOP.pop(user_id, None)
        if item_id:
            await database.update_shop_item(item_id, delivery_mode="manual")
            await msg.reply_html(f'{EMOJI_SUCCESS} 商品 <b>{name}</b> 已上架！（手动发货，{price}分，{"无限" if stock < 0 else f"库存{stock}"}）')
            items = await database.get_shop_items(chat_id)
            await context.bot.send_message(chat_id=update.effective_chat.id,
                text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城管理</b>',
                parse_mode="HTML", reply_markup=get_shop_admin_keyboard(str(chat_id), items))
        else:
            await msg.reply_html(f'{EMOJI_ERROR} 创建失败，请重试。')
        return

    # ── step: card data (auto mode) ──
    if step == "card":
        cards = [c.strip() for c in raw.split("\n") if c.strip()]
        if not cards:
            await msg.reply_html(f'{EMOJI_WARN} 卡密不能为空，请重新发送（一行一个）：', reply_markup=cancel_kb); return
        name = info.get("name", ""); price = info.get("price", 0)
        desc = info.get("desc", ""); stock = len(cards)
        item_id = await database.add_shop_item(chat_id, name, price, stock, desc)
        if item_id:
            await database.update_shop_item(item_id, delivery_mode="auto",
                card_data="\n".join(cards), stock=stock)
            _AWAIT_SHOP.pop(user_id, None)
            await msg.reply_html(f'{EMOJI_SUCCESS} 商品 <b>{name}</b> 已上架！（自动发卡，{stock}张）')
            items = await database.get_shop_items(chat_id)
            await context.bot.send_message(chat_id=update.effective_chat.id,
                text=f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城管理</b>',
                parse_mode="HTML", reply_markup=get_shop_admin_keyboard(str(chat_id), items))
        else:
            await msg.reply_html(f'{EMOJI_ERROR} 创建失败，请重试。')
        return


# ── /shop command ─────────────────────────────────────
async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        await update.message.reply_html(f'{EMOJI_WARN} 此命令仅限群组使用。'); return
    items = await database.get_shop_items(chat.id)
    active = [i for i in items if i["status"]]
    if not active:
        await update.message.reply_html(f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城</b>\n\n暂无商品上架。')
        return
    await update.message.reply_html(
        f'<tg-emoji emoji-id="{SHOP_EMOJI}">🛒</tg-emoji> <b>积分商城</b>\n\n使用积分兑换商品：',
        reply_markup=get_shop_list_keyboard(str(chat.id), active))


async def _check_admin(context, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False
