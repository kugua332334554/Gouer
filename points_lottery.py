# Points lottery — users spend points to enter, winners drawn randomly, DM notified
import asyncio
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
import database
from lang import t_sync, DEFAULT_LANG

logger = logging.getLogger(__name__)

LOTTERY_EMOJI = "5864128984798730231"
CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
ADD_EMOJI_ID = "5775937998948404844"
DELETE_EMOJI_ID = "6017288111279575194"
CONFETTI_EMOJI = "5404573776253825754"
COIN_EMOJI_ID = "5197688912457245639"
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'

_AWAIT_LOTTERY = {}  # user_id → {chat_id, field}


# ── Admin keyboard ────────────────────────────────────
def get_lottery_admin_keyboard(chat_id: str, lotteries: list) -> InlineKeyboardMarkup:
    keyboard = []
    for lt in lotteries:
        status_label = "进行中" if lt["status"] == "active" else "已结束"
        label = f'{lt["title"]} ({lt["ticket_price"]}分/票) [{status_label}]'
        row = [
            InlineKeyboardButton(label, callback_data=f"plt_detail_{chat_id}_{lt['id']}", icon_custom_emoji_id=LOTTERY_EMOJI),
            InlineKeyboardButton("删", callback_data=f"plt_del_{chat_id}_{lt['id']}", icon_custom_emoji_id=DELETE_EMOJI_ID)
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("创建抽奖", callback_data=f"plt_add_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


# ── Detail keyboard ───────────────────────────────────
def get_lottery_detail_keyboard(chat_id: str, lottery_id: int, lt: dict, entry_count: int) -> InlineKeyboardMarkup:
    keyboard = []
    if lt["status"] == "active":
        keyboard.append([InlineKeyboardButton(
            f'参与抽奖（{lt["ticket_price"]}分）', callback_data=f"plt_enter_{chat_id}_{lottery_id}", icon_custom_emoji_id=COIN_EMOJI_ID)])
        keyboard.append([InlineKeyboardButton(
            "开奖", callback_data=f"plt_draw_{chat_id}_{lottery_id}", icon_custom_emoji_id=LOTTERY_EMOJI)])
    keyboard.append([InlineKeyboardButton(
        "删除", callback_data=f"plt_del_{chat_id}_{lottery_id}", icon_custom_emoji_id=DELETE_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回列表", callback_data=f"plt_admin_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


# ── Callback handler ──────────────────────────────────
async def lottery_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data
    parts = data.split("_")

    # ── Admin panel ──
    if data.startswith("plt_admin_"):
        chat_id = int(parts[2])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能管理抽奖。", show_alert=True)
            return
        # 用户通过“取消”返回管理面板，清除挂起的输入等待状态
        _AWAIT_LOTTERY.pop(user_id, None)
        await query.answer()
        lotteries = await database.get_lotteries(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{LOTTERY_EMOJI}">🎰</tg-emoji> <b>积分抽奖管理</b>',
            parse_mode="HTML", reply_markup=get_lottery_admin_keyboard(str(chat_id), lotteries))
        return

    # ── Add lottery ──
    if data.startswith("plt_add_"):
        chat_id = int(parts[2])
        await query.answer()
        _AWAIT_LOTTERY[user_id] = {"chat_id": chat_id, "field": "title"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"plt_admin_{chat_id}")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{LOTTERY_EMOJI}">🎰</tg-emoji> <b>创建积分抽奖</b>\n\n'
            f'请发送抽奖信息：\n<code>标题|票价|奖品1,奖品2,...|中奖人数</code>\n\n'
            f'示例：\n<code>周末抽奖|50|VIP月卡,100积分,定制头像|3</code>',
            reply_markup=kb)
        return

    # ── Detail ──
    if data.startswith("plt_detail_"):
        chat_id = int(parts[2]); lottery_id = int(parts[3])
        await query.answer()
        lt = await database.get_lottery(lottery_id)
        if not lt:
            await query.answer("抽奖不存在", show_alert=True); return
        entries = await database.get_lottery_entry_count(lottery_id)
        prizes = lt["prize_list"].split(",") if lt["prize_list"] else ["神秘奖品"]
        text = (f'<tg-emoji emoji-id="{LOTTERY_EMOJI}">🎰</tg-emoji> <b>{lt["title"]}</b>\n\n'
                f'票价：{lt["ticket_price"]} 分/票\n'
                f'已参与：{entries} 人\n'
                f'中奖名额：{lt["max_winners"]} 人\n'
                f'奖品：{" | ".join(prizes)}\n'
                f'状态：{"进行中" if lt["status"] == "active" else "已结束"}')
        await query.edit_message_text(text=text, parse_mode="HTML",
            reply_markup=get_lottery_detail_keyboard(str(chat_id), lottery_id, lt, entries))
        return

    # ── Enter lottery ──
    if data.startswith("plt_enter_"):
        chat_id = int(parts[2]); lottery_id = int(parts[3])
        lt = await database.get_lottery(lottery_id)
        if not lt or lt["status"] != "active":
            await query.answer("该抽奖已结束", show_alert=True); return
        # check points
        pts = await database.get_user_points(chat_id, user_id)
        if pts < lt["ticket_price"]:
            await query.answer(f'积分不足！需要 {lt["ticket_price"]} 分，当前 {pts} 分', show_alert=True)
            return
        entered = await database.enter_lottery(lottery_id, user_id, user.username or user.first_name or "")
        if not entered:
            await query.answer("你已经参与过该抽奖了！", show_alert=True)
            return
        # deduct points
        await database.update_user_points_direct(chat_id, user_id, -lt["ticket_price"])
        await query.answer(f'参与成功！已扣除 {lt["ticket_price"]} 分')
        return

    # ── Draw ──
    if data.startswith("plt_draw_"):
        chat_id = int(parts[2]); lottery_id = int(parts[3])
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能开奖。", show_alert=True)
            return
        lt = await database.get_lottery(lottery_id)
        if not lt or lt["status"] != "active":
            await query.answer("该抽奖已结束", show_alert=True); return
        entries = await database.get_lottery_entries(lottery_id)
        if not entries:
            await query.answer("无人参与，无法开奖", show_alert=True); return

        max_w = min(lt["max_winners"], len(entries))
        winners = random.sample(entries, max_w)
        prizes = lt["prize_list"].split(",") if lt["prize_list"] else ["神秘奖品"]

        # mark lottery as finished
        await database.update_lottery(lottery_id, status="finished")
        await query.answer(f'已抽出 {max_w} 位中奖者！')

        # announce in group
        winner_names = "、".join(w["username"] or str(w["user_id"]) for w in winners)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{CONFETTI_EMOJI}">🎊</tg-emoji> <b>{lt["title"]} — 开奖结果</b>\n\n'
                 f'中奖人数：{max_w}\n中奖者：{winner_names}',
            parse_mode="HTML")

        # DM each winner with 0.5s interval
        for i, w in enumerate(winners):
            prize = prizes[i] if i < len(prizes) else prizes[-1]
            try:
                # get group title
                try:
                    chat = await context.bot.get_chat(chat_id)
                    group_title = chat.title or str(chat_id)
                except Exception:
                    group_title = str(chat_id)

                dm_text = (
                    f'<tg-emoji emoji-id="{CONFETTI_EMOJI}">🎊</tg-emoji> <b>恭喜中奖！</b>\n\n'
                    f'活动：<b>{lt["title"]}</b>\n'
                    f'群组：{group_title}\n\n'
                    f'您获得的奖品：<b>{prize}</b>\n\n'
                    f'请联系群管理员领取奖品。'
                )
                await context.bot.send_message(chat_id=w["user_id"], text=dm_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to DM winner {w['user_id']}: {e}")
            await asyncio.sleep(0.5)
        return

    # ── Delete ──
    if data.startswith("plt_del_"):
        chat_id = int(parts[2]); lottery_id = int(parts[3])
        await database.delete_lottery(lottery_id)
        await query.answer("已删除")
        lotteries = await database.get_lotteries(chat_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{LOTTERY_EMOJI}">🎰</tg-emoji> <b>积分抽奖管理</b>',
            parse_mode="HTML", reply_markup=get_lottery_admin_keyboard(str(chat_id), lotteries))
        return


# ── Input handler ─────────────────────────────────────
async def lottery_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    info = _AWAIT_LOTTERY.get(user_id)
    if not info: return

    msg = update.message
    if not msg or not msg.text: return

    chat_id = info["chat_id"]
    raw = msg.text.strip()

    if info["field"] == "title":
        # parse: 标题|票价|奖品1,奖品2|中奖人数
        parts = raw.split("|")
        if len(parts) < 2:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"plt_admin_{chat_id}")]])
            await msg.reply_html(f'{EMOJI_WARN} 格式错误！\n<code>标题|票价|奖品列表|中奖人数</code>', reply_markup=kb)
            return
        title = parts[0].strip()
        try: price = int(parts[1].strip())
        except ValueError:
            await msg.reply_html(f'{EMOJI_WARN} 票价必须是数字！'); return
        prizes = parts[2].strip() if len(parts) > 2 else "神秘奖品"
        max_w = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().isdigit() else 1
        if not title or price <= 0:
            await msg.reply_html(f'{EMOJI_WARN} 标题和票价不能为空！'); return

        lt_id = await database.add_lottery(chat_id, title, price, prizes, max_w)
        if lt_id:
            _AWAIT_LOTTERY.pop(user_id, None)
            await msg.reply_html(f'{EMOJI_SUCCESS} 抽奖 <b>{title}</b> 已创建！（{price}分/票，{max_w}名中奖者）')
            lotteries = await database.get_lotteries(chat_id)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f'<tg-emoji emoji-id="{LOTTERY_EMOJI}">🎰</tg-emoji> <b>积分抽奖管理</b>',
                parse_mode="HTML", reply_markup=get_lottery_admin_keyboard(str(chat_id), lotteries))
        else:
            await msg.reply_html('创建失败，请重试。')
        return
