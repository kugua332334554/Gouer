import asyncio
import logging
import datetime
import random
import json
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions
from telegram.ext import ContextTypes
import database
from database import validate_column_name
from lang import t

logger = logging.getLogger(__name__)
logger.info("choujiang module loaded")

CHECK_EMOJI_ID = "5776375003280838798"
CROSS_EMOJI_ID = "5778527486270770928"
CLOCK_EMOJI_ID = "5776213190387961618"
GIFT_EMOJI_ID = "5864128984798730231"
GIFT2_EMOJI_ID = "6174734048913531742"
GIFT3_EMOJI_ID = "5118849582238795805"
CROWN_EMOJI_ID = "5807461353799030682"
TROPHY_EMOJI_ID = "6150138841383574191"
MEGA_EMOJI_ID = "5771695636411847302"
ADD_EMOJI_ID = "5775937998948404844"
ADD2_EMOJI_ID = "5258362837411045098"
BACK_EMOJI_ID = "5875082500023258804"
DELETE_EMOJI_ID = "6017288111279575194"
WARN_EMOJI_ID = "5447644880824181073"
DICE_EMOJI_ID = "5933629020301169337"
STAR_EMOJI_ID = "6323440286445867472"
GOLDSTAR_EMOJI_ID = "5208801655004350721"
DIAMOND_EMOJI_ID = "5332814802702056788"
SETTINGS_EMOJI_ID = "5931409969613116639"
CHART_EMOJI_ID = "5994378914636500516"

EMOJI_ERROR = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'

LOTTERY_TYPES = {"general": "通用抽奖", "points": "积分抽奖", "activity": "群活跃抽奖", "dice": "骰子点数抽奖", "report": "报道抽奖"}
DRAW_METHODS = {"time": "到达时间开奖", "count": "到达人数开奖"}

_AWAIT_CHOUJIANG_INPUT = {}


def _extract_chat_id(data: str) -> int:
    # 回调格式各异，从所有 _ 分段中找第一个像 chat_id 的（负数大整数）
    for part in data.split("_"):
        if part.startswith("-") and len(part) > 5:
            return int(part)
    # fallback: 旧格式 cj_xxxx_{chat_id}
    return int(data.split("_")[2])


async def get_choujiang_settings(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, pin_lottery, pin_result, delete_entry, push_channel, push_enabled FROM group_choujiang_settings WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {"chat_id": row[0], "pin_lottery": bool(row[1]), "pin_result": bool(row[2]), "delete_entry": row[3] or 0, "push_channel": row[4] or "", "push_enabled": bool(row[5])}
    except Exception as e:
        logger.error(f"get_choujiang_settings err: {e}", exc_info=True)
    return {"chat_id": chat_id, "pin_lottery": True, "pin_result": True, "delete_entry": 0, "push_channel": "", "push_enabled": False}


async def update_choujiang_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_choujiang_settings (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_choujiang_settings SET {', '.join(parts)} WHERE chat_id = %s", vals)
    except Exception as e:
        logger.error(f"update_choujiang_settings err: {e}", exc_info=True)


async def create_choujiang(chat_id: int, creator_id: int, ctype: str, title: str, prizes_json: str, winners: int, entry_cost: int, draw_method: str, draw_value: str, report_group_id: int = 0, report_keyword: str = "", report_group_link: str = "") -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                if draw_method == "count":
                    await cur.execute(
                        "INSERT INTO group_choujiang (chat_id, creator_id, type, title, prize_description, winner_count, entry_cost, draw_method, draw_count, report_group_id, report_keyword, report_group_link) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (chat_id, creator_id, ctype, title, prizes_json, winners, entry_cost, draw_method, int(draw_value), report_group_id, report_keyword, report_group_link))
                else:
                    draw_time = datetime.datetime.strptime(draw_value, "%Y-%m-%d %H:%M")
                    await cur.execute(
                        "INSERT INTO group_choujiang (chat_id, creator_id, type, title, prize_description, winner_count, entry_cost, draw_method, draw_time, report_group_id, report_keyword, report_group_link) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (chat_id, creator_id, ctype, title, prizes_json, winners, entry_cost, draw_method, draw_time, report_group_id, report_keyword, report_group_link))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"create_choujiang err: {e}", exc_info=True)
        return 0


async def get_choujiang_list(chat_id: int, status_filter: str = None) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                if status_filter:
                    await cur.execute("SELECT id, chat_id, creator_id, type, title, prize_description, winner_count, entry_cost, draw_method, draw_count, draw_time, report_group_id, report_keyword, report_group_link, status, message_id, created_at FROM group_choujiang WHERE chat_id = %s AND status = %s ORDER BY id DESC", (chat_id, status_filter))
                else:
                    await cur.execute("SELECT id, chat_id, creator_id, type, title, prize_description, winner_count, entry_cost, draw_method, draw_count, draw_time, report_group_id, report_keyword, report_group_link, status, message_id, created_at FROM group_choujiang WHERE chat_id = %s ORDER BY id DESC", (chat_id,))
                return [_row_to_dict(row) for row in await cur.fetchall()]
    except Exception as e:
        logger.error(f"get_choujiang_list err: {e}", exc_info=True)
        return []


async def get_choujiang_by_id(lottery_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, chat_id, creator_id, type, title, prize_description, winner_count, entry_cost, draw_method, draw_count, draw_time, report_group_id, report_keyword, report_group_link, status, message_id, created_at FROM group_choujiang WHERE id = %s", (lottery_id,))
                row = await cur.fetchone()
                return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"get_choujiang_by_id err: {e}", exc_info=True)
        return None


async def _refund_entries(lottery_id: int):
    """取消抽奖或过期时退还所有参与者积分。"""
    try:
        lottery = await get_choujiang_by_id(lottery_id)
        if not lottery or lottery["entry_cost"] <= 0:
            return
        entries = await get_entries(lottery_id)
        if not entries:
            return
        from database import update_user_points_direct
        for entry in entries:
            try:
                await update_user_points_direct(lottery["chat_id"], entry["user_id"], lottery["entry_cost"])
            except Exception:
                pass
        logger.info(f"refunded {len(entries)} entries for lottery {lottery_id}, {lottery['entry_cost']} pts each")
    except Exception as e:
        logger.error(f"_refund_entries err: {e}")


def _row_to_dict(row) -> dict:
    return {"id": row[0], "chat_id": row[1], "creator_id": row[2], "type": row[3], "title": row[4],
            "prize_description": row[5] or "[]", "winner_count": row[6] or 1, "entry_cost": row[7] or 0,
            "draw_method": row[8], "draw_count": row[9] or 0, "draw_time": row[10],
            "report_group_id": row[11] or 0, "report_keyword": row[12] or "",
            "report_group_link": row[13] or "",
            "status": row[14], "message_id": row[15], "created_at": row[16]}


async def update_choujiang(lottery_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(lottery_id)
                await cur.execute(f"UPDATE group_choujiang SET {', '.join(parts)} WHERE id = %s", vals)
    except Exception as e:
        logger.error(f"update_choujiang err: {e}", exc_info=True)


async def add_entry(lottery_id: int, user_id: int, entry_data: str = "") -> bool:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM group_choujiang_entries WHERE lottery_id = %s AND user_id = %s", (lottery_id, user_id))
                if await cur.fetchone():
                    return False
                await cur.execute("INSERT INTO group_choujiang_entries (lottery_id, user_id, entry_data) VALUES (%s, %s, %s)", (lottery_id, user_id, entry_data))
                return True
    except Exception as e:
        logger.error(f"add_entry err: {e}", exc_info=True)
        return False


async def get_entry_count(lottery_id: int) -> int:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM group_choujiang_entries WHERE lottery_id = %s", (lottery_id,))
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


async def get_entries(lottery_id: int) -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id, entry_data FROM group_choujiang_entries WHERE lottery_id = %s", (lottery_id,))
                return [{"user_id": row[0], "entry_data": row[1] or ""} for row in await cur.fetchall()]
    except Exception:
        return []


async def get_active_time_lotteries() -> list:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, chat_id, creator_id, type, title, prize_description, winner_count, entry_cost, draw_method, draw_count, draw_time, report_group_id, report_keyword, report_group_link, status, message_id, created_at FROM group_choujiang WHERE status = 'active' AND draw_method = 'time' AND draw_time IS NOT NULL")
                return [_row_to_dict(row) for row in await cur.fetchall()]
    except Exception as e:
        logger.error(f"get_active_time_lotteries err: {e}", exc_info=True)
        return []


async def get_stats(chat_id: int) -> dict:
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*), SUM(CASE WHEN status='drawn' THEN 1 ELSE 0 END), SUM(CASE WHEN status='active' THEN 1 ELSE 0 END), SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) FROM group_choujiang WHERE chat_id = %s", (chat_id,))
                row = await cur.fetchone()
                return {"total": row[0] or 0, "drawn": row[1] or 0, "active": row[2] or 0, "cancelled": row[3] or 0}
    except Exception:
        return {"total": 0, "drawn": 0, "active": 0, "cancelled": 0}


async def draw_winners(lottery_id: int) -> list:
    entries = await get_entries(lottery_id)
    lottery = await get_choujiang_by_id(lottery_id)
    if not lottery or not entries:
        return []
    winner_count = min(lottery["winner_count"], len(entries))
    winners = random.sample(entries, winner_count)
    winner_ids = [w["user_id"] for w in winners]
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                for wid in winner_ids:
                    await cur.execute("INSERT INTO group_choujiang_winners (lottery_id, user_id) VALUES (%s, %s)", (lottery_id, wid))
    except Exception:
        pass
    await update_choujiang(lottery_id, status="drawn")
    return winner_ids


def get_lottery_text(lottery: dict, entry_count: int, chat_title: str = "") -> str:
    ctype = LOTTERY_TYPES.get(lottery["type"], lottery["type"])
    if lottery["type"] == "dice":
        draw_info = f"投出 {lottery['draw_count']} 点即可参与 | 已参与 {entry_count} 人"
    elif lottery["draw_method"] == "count":
        draw_info = f"参与 {entry_count}/{lottery['draw_count']} 人"
    else:
        dt = lottery["draw_time"]
        draw_info = f"开奖时间 {dt.strftime('%Y-%m-%d %H:%M') if isinstance(dt, datetime.datetime) else str(dt)[:16]}"
    prizes = []
    try:
        prizes = json.loads(lottery["prize_description"] or "[]")
    except Exception:
        pass
    prize_text = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(prizes)) if prizes else "神秘奖品"
    text = (
        f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>[{chat_title}] {lottery["title"]}</b>\n\n'
        f'类型：{ctype}\n'
        f'奖品：\n{prize_text}\n'
        f'中奖人数：{lottery["winner_count"]} 人\n'
        f'{draw_info}\n'
    )
    if lottery["entry_cost"] > 0:
        text += f'参与费用：{lottery["entry_cost"]} 积分\n'
    if lottery["type"] == "report" and lottery.get("report_group_id"):
        link = lottery.get("report_group_link", "")
        link_text = f'\n<tg-emoji emoji-id="5203948303305158848">🔗</tg-emoji> <a href="{link}">点击加入报道群</a>' if link else ""
        text += f'\n<tg-emoji emoji-id="{MEGA_EMOJI_ID}">📢</tg-emoji> <b>参与方式：</b>\n前往目标群发送关键词 <code>{lottery.get("report_keyword", "")}</code> 即可参与{link_text}\n'
    return text


def get_lottery_keyboard(lottery_id: int, lottery_type: str = "general") -> InlineKeyboardMarkup:
    btn_text = "积分参与" if lottery_type == "points" else "参与抽奖"
    return InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data=f"cj_enter_{lottery_id}", icon_custom_emoji_id=GIFT_EMOJI_ID)]])


def get_draw_keyboard(lottery_id: int, chat_id: str, status: str = "active") -> InlineKeyboardMarkup:
    kb = []
    if status == "active":
        kb.append([InlineKeyboardButton("提前开奖", callback_data=f"cj_draw_{lottery_id}", icon_custom_emoji_id=DICE_EMOJI_ID),
                   InlineKeyboardButton("取消抽奖", callback_data=f"cj_cancel_{lottery_id}", icon_custom_emoji_id=CROSS_EMOJI_ID)])
    kb.append([InlineKeyboardButton("« 返回管理", callback_data=f"cj_manage_{chat_id}_all_1")])
    return InlineKeyboardMarkup(kb)


def get_create_type_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    keyboard = []
    for k, v in LOTTERY_TYPES.items():
        keyboard.append([InlineKeyboardButton(v, callback_data=f"cj_createtype_{chat_id}_{k}", icon_custom_emoji_id=GIFT3_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"group_choujiang_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_create_method_keyboard(chat_id: str, ctype: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("到达人数开奖", callback_data=f"cj_createmethod_{chat_id}_{ctype}_count", icon_custom_emoji_id=CHART_EMOJI_ID)],
        [InlineKeyboardButton("到达时间开奖", callback_data=f"cj_createmethod_{chat_id}_{ctype}_time", icon_custom_emoji_id=CLOCK_EMOJI_ID)],
        [InlineKeyboardButton("« 返回", callback_data=f"group_choujiang_{chat_id}")]
    ])


def get_confirm_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("添加奖品", callback_data=f"cj_addprize_{chat_id}", icon_custom_emoji_id=ADD2_EMOJI_ID)],
        [InlineKeyboardButton("删除最后奖品", callback_data=f"cj_delprize_{chat_id}", icon_custom_emoji_id=DELETE_EMOJI_ID)],
        [InlineKeyboardButton("确认创建", callback_data=f"cj_docreate_{chat_id}", icon_custom_emoji_id=CHECK_EMOJI_ID),
         InlineKeyboardButton("取消", callback_data=f"group_choujiang_{chat_id}")]
    ])


def get_settings_keyboard(chat_id: str, settings: dict) -> InlineKeyboardMarkup:
    pin_lottery_text = "发布置顶:开" if settings["pin_lottery"] else "发布置顶:关"
    pin_result_text = "结果置顶:开" if settings["pin_result"] else "结果置顶:关"
    del_text = f"删除口令:{settings['delete_entry']}秒" if settings["delete_entry"] > 0 else "删除口令:关"
    import config
    push_on = settings.get("push_enabled", False)
    if not config.PUSH_CHANNEL:
        push_text = "推送: 未配置"
        push_cb = "noop"
    else:
        push_text = "推送:开" if push_on else "推送:关"
        push_cb = f"cj_set_push_{chat_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(pin_lottery_text, callback_data=f"cj_set_pinlottery_{chat_id}", icon_custom_emoji_id=GOLDSTAR_EMOJI_ID if settings["pin_lottery"] else CROSS_EMOJI_ID)],
        [InlineKeyboardButton(pin_result_text, callback_data=f"cj_set_pinresult_{chat_id}", icon_custom_emoji_id=DIAMOND_EMOJI_ID if settings["pin_result"] else CROSS_EMOJI_ID)],
        [InlineKeyboardButton(del_text, callback_data=f"cj_set_delentry_{chat_id}", icon_custom_emoji_id=DELETE_EMOJI_ID)],
        [InlineKeyboardButton(push_text, callback_data=push_cb, icon_custom_emoji_id=MEGA_EMOJI_ID if push_on else CROSS_EMOJI_ID)],
        [InlineKeyboardButton("« 返回抽奖管理", callback_data=f"group_choujiang_{chat_id}")]
    ])


def get_del_entry_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("关闭删除", callback_data=f"cj_doset_delentry_{chat_id}_0")],
        [InlineKeyboardButton("5秒", callback_data=f"cj_doset_delentry_{chat_id}_5"), InlineKeyboardButton("10秒", callback_data=f"cj_doset_delentry_{chat_id}_10")],
        [InlineKeyboardButton("30秒", callback_data=f"cj_doset_delentry_{chat_id}_30"), InlineKeyboardButton("60秒", callback_data=f"cj_doset_delentry_{chat_id}_60")],
        [InlineKeyboardButton("« 返回", callback_data=f"cj_settings_{chat_id}")]
    ])


def _format_create_summary(state: dict) -> str:
    ctype = LOTTERY_TYPES.get(state["ctype"], state["ctype"])
    method = DRAW_METHODS.get(state["method"], state["method"])
    prizes_text = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(state.get("prizes", []))) if state.get("prizes") else "（尚未添加奖品）"
    text = (
        f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>创建抽奖确认</b>\n\n'
        f'类型：{ctype}\n'
        f'开奖方式：{method}\n'
        f'标题：{state["title"]}\n'
        f'中奖人数：{state["winners"]} 人\n'
    )
    if state["method"] == "count":
        text += f'所需人数：{state["draw_value"]} 人\n'
    else:
        text += f'开奖时间：{state["draw_value"]}\n'
    if state["ctype"] == "points":
        text += f'参与积分：{state.get("cost", 0)} 分\n'
    if state["ctype"] == "report":
        text += f'报道群：{state.get("report_group_id", "")}\n报道关键词：{state.get("report_keyword", "")}\n'
    text += f'\n奖品列表：\n{prizes_text}'
    return text


async def send_choujiang_panel(context, chat_id: int, target_chat_id: int, user_id: int = 0):
    stats = await get_stats(chat_id)
    title = await t(user_id, "choujiang_title") if user_id else "抽奖管理"
    stats_text = await t(user_id, "choujiang_stats") if user_id else "创建的抽奖次数"
    drawn_text = await t(user_id, "choujiang_drawn") if user_id else "已开奖"
    active_text = await t(user_id, "choujiang_active") if user_id else "未开奖"
    canc_text = await t(user_id, "choujiang_cancelled") if user_id else "取消"
    text = (
        f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>{title}</b>\n\n'
        f'{stats_text}: {stats["total"]}\n'
        f'{drawn_text}: {stats["drawn"]}\n'
        f'{active_text}: {stats["active"]}\n'
        f'{canc_text}: {stats["cancelled"]}\n'
    )
    active = await get_choujiang_list(chat_id, "active")
    keyboard = []
    for cj in active[:5]:
        cnt = await get_entry_count(cj["id"])
        keyboard.append([InlineKeyboardButton(f'{cj["title"]} ({cnt}人)', callback_data=f"cj_detail_{chat_id}_{cj['id']}", icon_custom_emoji_id=GIFT2_EMOJI_ID)])
    keyboard.append([
        InlineKeyboardButton("创建抽奖", callback_data=f"cj_create_{chat_id}", icon_custom_emoji_id=ADD_EMOJI_ID),
        InlineKeyboardButton("抽奖设置", callback_data=f"cj_settings_{chat_id}", icon_custom_emoji_id=SETTINGS_EMOJI_ID)
    ])
    keyboard.append([InlineKeyboardButton("管理抽奖", callback_data=f"cj_manage_{chat_id}_all_1", icon_custom_emoji_id=GIFT2_EMOJI_ID)])
    keyboard.append([InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")])
    await context.bot.send_message(chat_id=target_chat_id, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


STATUS_LABELS = {"all": "全部", "active": "未开奖", "drawn": "已开奖", "cancelled": "已取消"}
PER_PAGE = 5


def get_manage_keyboard(chat_id: str, lotteries: list, page: int, total_pages: int, current_filter: str) -> InlineKeyboardMarkup:
    kb = []
    # 列表
    for cj in lotteries:
        kb.append([InlineKeyboardButton(
            cj["title"],
            callback_data=f"cj_detail_{chat_id}_{cj['id']}",
            icon_custom_emoji_id=GIFT2_EMOJI_ID
        )])
    # 翻页
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀", callback_data=f"cj_manage_{chat_id}_{current_filter}_{page - 1}", icon_custom_emoji_id=GIFT_EMOJI_ID))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶", callback_data=f"cj_manage_{chat_id}_{current_filter}_{page + 1}", icon_custom_emoji_id=GIFT_EMOJI_ID))
    if nav:
        kb.append(nav)
    # 筛选
    filter_row = []
    for fk, fv in STATUS_LABELS.items():
        prefix = "● " if fk == current_filter else ""
        filter_row.append(InlineKeyboardButton(
            f'{prefix}{fv}',
            callback_data=f"cj_manage_{chat_id}_{fk}_1",
            icon_custom_emoji_id=GIFT2_EMOJI_ID
        ))
    kb.append(filter_row)
    kb.append([InlineKeyboardButton("« 返回抽奖管理", callback_data=f"group_choujiang_{chat_id}")])
    return InlineKeyboardMarkup(kb)


async def send_manage_panel(context, chat_id: int, target_chat_id: int, filter_status: str = "all", page: int = 1):
    stats = await get_stats(chat_id)
    if filter_status == "all":
        all_list = await get_choujiang_list(chat_id)
    else:
        all_list = await get_choujiang_list(chat_id, filter_status)
    total = len(all_list)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    start = (page - 1) * PER_PAGE
    page_items = all_list[start:start + PER_PAGE]

    text = (
        f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>管理抽奖</b>\n\n'
        f'总次数: {stats["total"]} | 已开奖: {stats["drawn"]} | 未开奖: {stats["active"]} | 取消: {stats["cancelled"]}\n'
        f'当前筛选: {STATUS_LABELS.get(filter_status, "全部")} ({total}条)\n'
    )
    await context.bot.send_message(
        chat_id=target_chat_id, text=text, parse_mode="HTML",
        reply_markup=get_manage_keyboard(str(chat_id), page_items, page, total_pages, filter_status)
    )


async def choujiang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    if data.startswith("cj_enter_"):
        lottery_id = int(data.split("_")[-1])
        lottery = await get_choujiang_by_id(lottery_id)
        if not lottery or lottery["status"] != "active":
            await query.answer("该抽奖已结束或不存在", show_alert=True)
            return
        if lottery["type"] == "dice":
            target = lottery.get("draw_count", 1) or 1
            await query.answer(f"请发送骰子，投出 {target} 点！", show_alert=True)
            # 额外发一条消息提醒发骰子
            user_mention = f'<a href="tg://user?id={user_id}">{query.from_user.first_name}</a>'
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f'<tg-emoji emoji-id="{DICE_EMOJI_ID}">🎲</tg-emoji> {user_mention} 请发送骰子，投出 <b>{target}</b> 点即可参与「{lottery["title"]}」！',
                parse_mode="HTML"
            )
            return
        if lottery["type"] == "report":
            keyword = lottery.get("report_keyword", "")
            gid = lottery.get("report_group_id", 0)
            await query.answer(f"报道抽奖！请在目标群发送关键词「{keyword}」参与", show_alert=True)
            return
        if lottery["type"] == "points" and lottery["entry_cost"] > 0:
            from database import get_user_points, update_user_points_direct
            pts = await get_user_points(lottery["chat_id"], user_id)
            if pts < lottery["entry_cost"]:
                await query.answer(f"积分不足！需要 {lottery['entry_cost']} 积分，你只有 {pts} 积分", show_alert=True)
                return
            await update_user_points_direct(lottery["chat_id"], user_id, -lottery["entry_cost"])
        added = await add_entry(lottery_id, user_id)
        if not added:
            await query.answer("你已经参与过了！", show_alert=True)
            return
        await query.answer("✅ 参与成功！")
        cnt = await get_entry_count(lottery_id)
        if lottery["draw_method"] == "count" and cnt >= lottery["draw_count"]:
            await do_draw(context, lottery, lottery["chat_id"])
            try:
                await query.message.delete()
            except Exception:
                pass
            return
        try:
            new_text = get_lottery_text(lottery, cnt)
            await query.message.edit_text(text=new_text, parse_mode="HTML", reply_markup=get_lottery_keyboard(lottery_id, lottery["type"]))
        except Exception:
            pass
        settings = await get_choujiang_settings(lottery["chat_id"])
        if settings["delete_entry"] > 0:
            asyncio.create_task(_delete_after(context.bot, lottery["chat_id"], query.message.message_id, settings["delete_entry"]))
        return

    try:
        chat_id = _extract_chat_id(data)
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await query.answer("⚠️ 只有管理员才能管理抽奖。", show_alert=True)
            return
    except Exception:
        return

    if data.startswith("group_choujiang_"):
        await query.answer()
        await query.message.delete()
        await send_choujiang_panel(context, chat_id, update.effective_chat.id, user_id)
        return

    if data.startswith("cj_create_"):
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>创建抽奖</b>\n\n请选择抽奖类型：', parse_mode="HTML", reply_markup=get_create_type_keyboard(str(chat_id)))
        return

    if data.startswith("cj_createtype_"):
        ctype = data.split("_")[-1]
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>创建 {LOTTERY_TYPES.get(ctype, ctype)}</b>\n\n请选择开奖方式：', parse_mode="HTML", reply_markup=get_create_method_keyboard(str(chat_id), ctype))
        return

    if data.startswith("cj_createmethod_"):
        parts = data.split("_")
        ctype, method = parts[3], parts[4]
        await query.answer()
        await query.message.delete()
        _AWAIT_CHOUJIANG_INPUT[user_id] = {"type": "create_title", "chat_id": str(chat_id), "ctype": ctype, "method": method, "prizes": []}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id}")]])
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>第一步：输入抽奖标题</b>\n\n类型：{LOTTERY_TYPES[ctype]}\n开奖：{DRAW_METHODS[method]}\n\n请发送抽奖标题：', parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("cj_addprize_"):
        await query.answer()
        await query.message.delete()
        _AWAIT_CHOUJIANG_INPUT[user_id]["type"] = "create_prize"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id}")]])
        await context.bot.send_message(chat_id=update.effective_chat.id, text="请发送奖品描述（例如：iPhone 15、红包100元）：", reply_markup=kb)
        return

    if data.startswith("cj_delprize_"):
        state = _AWAIT_CHOUJIANG_INPUT.get(user_id, {})
        if state.get("prizes"):
            state["prizes"].pop()
            await query.answer("已删除最后一个奖品")
        else:
            await query.answer("没有奖品可删除", show_alert=True)
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=_format_create_summary(state), parse_mode="HTML", reply_markup=get_confirm_keyboard(str(chat_id)))
        return

    if data.startswith("cj_docreate_"):
        state = _AWAIT_CHOUJIANG_INPUT.pop(user_id, None)
        if not state:
            await query.answer("创建数据已过期", show_alert=True)
            return
        await query.answer("正在创建...")
        await query.message.delete()
        prizes_json = json.dumps(state.get("prizes", []), ensure_ascii=False)
        lottery_id = await create_choujiang(chat_id, user_id, state["ctype"], state["title"], prizes_json, state["winners"],
                                              state.get("cost", 0), state["method"], state["draw_value"],
                                              state.get("report_group_id", 0), state.get("report_keyword", ""),
                                              state.get("report_group_link", ""))
        if lottery_id:
            lottery = await get_choujiang_by_id(lottery_id)
            try:
                chat_info = await context.bot.get_chat(chat_id)
                chat_title = chat_info.title
            except Exception:
                chat_title = ""
            ltext = get_lottery_text(lottery, 0, chat_title)
            lkb = get_lottery_keyboard(lottery_id, state["ctype"])
            settings = await get_choujiang_settings(chat_id)
            sent_msg = await context.bot.send_message(chat_id=chat_id, text=ltext, parse_mode="HTML", reply_markup=lkb)
            await update_choujiang(lottery_id, message_id=sent_msg.message_id)
            # 骰子抽奖额外发一条骰子消息
            if state["ctype"] == "dice":
                try:
                    await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
                except Exception:
                    pass
            if settings["pin_lottery"]:
                try:
                    await context.bot.pin_chat_message(chat_id=chat_id, message_id=sent_msg.message_id, disable_notification=False)
                except Exception:
                    pass
            import config
            if config.PUSH_CHANNEL and settings.get("push_enabled", False):
                # 获取群邀请链接
                invite_link = ""
                try:
                    chat_info = await context.bot.get_chat(chat_id)
                    if chat_info.username:
                        invite_link = f"https://t.me/{chat_info.username}"
                    elif chat_info.invite_link:
                        invite_link = chat_info.invite_link
                    else:
                        try:
                            link_obj = await context.bot.create_chat_invite_link(chat_id, member_limit=1)
                            invite_link = link_obj.invite_link
                        except Exception:
                            pass
                except Exception:
                    pass
                prizes_list = state.get("prizes", [])
                prizes_str = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(prizes_list)) if prizes_list else "神秘奖品"
                push_text = (
                    f'<tg-emoji emoji-id="6325537750904737351">🌟</tg-emoji> <b>{chat_title} 发起了抽奖</b>\n\n'
                    f'<tg-emoji emoji-id="5929192117220937925">⭐️</tg-emoji> 奖品:\n{prizes_str[:300]}\n'
                )
                if invite_link:
                    push_text += f'\n<tg-emoji emoji-id="5203948303305158848">🍷</tg-emoji> <a href="{invite_link}">点击加入群组</a>\n'
                push_text += f'\n中奖人数: {state["winners"]} 人'
                try:
                    await context.bot.send_message(chat_id=config.PUSH_CHANNEL, text=push_text, parse_mode="HTML")
                except Exception:
                    pass
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f'{EMOJI_SUCCESS} 抽奖「{state["title"]}」已创建并发布！', parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"{EMOJI_ERROR} 创建失败。", parse_mode="HTML")
        return

    if data.startswith("cj_detail_"):
        lottery_id = int(data.split("_")[-1])
        lottery = await get_choujiang_by_id(lottery_id)
        if not lottery:
            await query.answer("抽奖不存在", show_alert=True)
            return
        await query.answer()
        await query.message.delete()
        cnt = await get_entry_count(lottery_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=get_lottery_text(lottery, cnt), parse_mode="HTML", reply_markup=get_draw_keyboard(lottery_id, str(chat_id), lottery["status"]))
        return

    if data.startswith("cj_manage_"):
        parts = data.split("_")
        filter_status = parts[3] if len(parts) > 3 else "all"
        page = int(parts[4]) if len(parts) > 4 else 1
        await query.answer()
        await query.message.delete()
        await send_manage_panel(context, chat_id, update.effective_chat.id, filter_status, page)
        return

    if data.startswith("cj_draw_"):
        lottery_id = int(data.split("_")[-1])
        await query.answer()
        await query.message.delete()
        await do_draw(context, await get_choujiang_by_id(lottery_id), chat_id, update.effective_chat.id)
        return

    if data.startswith("cj_cancel_"):
        lottery_id = int(data.split("_")[-1])
        await update_choujiang(lottery_id, status="cancelled")
        # 退还所有参与者的积分
        await _refund_entries(lottery_id)
        await query.answer("已取消，积分已退还")
        await query.message.delete()
        await send_manage_panel(context, chat_id, update.effective_chat.id, "all", 1)
        return

    if data.startswith("cj_settings_"):
        await query.answer()
        await query.message.delete()
        settings = await get_choujiang_settings(chat_id)
        import config
        if not config.PUSH_CHANNEL:
            push_display = "未配置"
        else:
            push_display = "开启" if settings.get("push_enabled", False) else "关闭"
        text = f'<tg-emoji emoji-id="{SETTINGS_EMOJI_ID}">⚙️</tg-emoji> <b>抽奖设置</b>\n\n发布置顶:\n└ 发布抽奖消息群内置顶\n结果置顶:\n└ 中奖结果消息群内置顶\n删除口令:\n└ {"{:.0f}".format(settings["delete_entry"])+"秒后自动删除" if settings["delete_entry"]>0 else "关闭"}\n抽奖推送:\n└ {push_display}'
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML", reply_markup=get_settings_keyboard(str(chat_id), settings))
        return

    if data.startswith("cj_set_pinlottery_"):
        s = await get_choujiang_settings(chat_id)
        await update_choujiang_settings(chat_id, pin_lottery=not s["pin_lottery"])
        await query.answer("已切换")
        await query.message.delete()
        s = await get_choujiang_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'{EMOJI_SUCCESS} 已更新', parse_mode="HTML", reply_markup=get_settings_keyboard(str(chat_id), s))
        return

    if data.startswith("cj_set_pinresult_"):
        s = await get_choujiang_settings(chat_id)
        await update_choujiang_settings(chat_id, pin_result=not s["pin_result"])
        await query.answer("已切换")
        await query.message.delete()
        s = await get_choujiang_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'{EMOJI_SUCCESS} 已更新', parse_mode="HTML", reply_markup=get_settings_keyboard(str(chat_id), s))
        return

    if data.startswith("cj_set_push_"):
        s = await get_choujiang_settings(chat_id)
        new_val = not s.get("push_enabled", False)
        await update_choujiang_settings(chat_id, push_enabled=new_val)
        await query.answer(f'推送已{"开启" if new_val else "关闭"}')
        await query.message.delete()
        s = await get_choujiang_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'{EMOJI_SUCCESS} 已更新', parse_mode="HTML", reply_markup=get_settings_keyboard(str(chat_id), s))
        return

    if data.startswith("cj_set_delentry_"):
        await query.answer()
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text="选择删除延迟时间：", reply_markup=get_del_entry_keyboard(str(chat_id)))
        return

    if data.startswith("cj_doset_delentry_"):
        val = int(data.split("_")[-1])
        await update_choujiang_settings(chat_id, delete_entry=val)
        await query.answer(f"删除口令：{'关闭' if val == 0 else f'{val}秒'}")
        await query.message.delete()
        s = await get_choujiang_settings(chat_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f'{EMOJI_SUCCESS} 已更新', parse_mode="HTML", reply_markup=get_settings_keyboard(str(chat_id), s))
        return

async def choujiang_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    message = update.message
    if message is None:
        return

    chat_id_now = update.effective_chat.id if update.effective_chat else 0

    # 骰子抽奖检测 — 用户投出骰子，值匹配即参与
    if message.dice and chat_id_now:
        dice_val = message.dice.value
        try:
            from database import db_pool
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, chat_id, draw_count FROM group_choujiang WHERE chat_id=%s AND type='dice' AND status='active'",
                        (chat_id_now,))
                    for row in await cur.fetchall():
                        lid, l_chat_id, target = row
                        if dice_val != (target or 1):
                            continue
                        # 已参与过？
                        await cur.execute("SELECT 1 FROM group_choujiang_entries WHERE lottery_id=%s AND user_id=%s", (lid, user_id))
                        if await cur.fetchone():
                            continue
                        await cur.execute("INSERT INTO group_choujiang_entries (lottery_id, user_id, entry_data) VALUES (%s, %s, %s)", (lid, user_id, f"dice:{dice_val}"))
                        logger.info(f"dice lottery entry: user={user_id} lottery={lid} dice={dice_val}")
                        # 检查是否达到开奖条件
                        await cur.execute("SELECT COUNT(*) FROM group_choujiang_entries WHERE lottery_id=%s", (lid,))
                        cnt = (await cur.fetchone())[0]
                        await cur.execute("SELECT draw_count FROM group_choujiang WHERE id=%s", (lid,))
                        lrow = await cur.fetchone()
                        draw_cnt = lrow[0] if lrow else 0
                        if cnt >= draw_cnt:
                            asyncio.create_task(_auto_draw_from_db(context, lid, l_chat_id))
        except Exception as e:
            logger.error(f"dice lottery check err: {e}")

    if not message.text:
        return

    # 报道抽奖关键词检测（无论是否在 await 状态都检查）
    raw = message.text.strip()
    chat_id_now = update.effective_chat.id if update.effective_chat else 0
    if chat_id_now and raw:
        # 查当前群是否有 active 的报道抽奖用此关键词
        try:
            from database import db_pool
            async with db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, chat_id, report_keyword, draw_method, draw_count, entry_cost FROM group_choujiang WHERE report_group_id=%s AND report_keyword=%s AND status='active'",
                        (chat_id_now, raw))
                    rows = await cur.fetchall()
                    for row in rows:
                        lid, l_chat_id, kw, method, draw_cnt_val, cost = row
                        # 检查是否已参与
                        await cur.execute("SELECT 1 FROM group_choujiang_entries WHERE lottery_id=%s AND user_id=%s", (lid, user_id))
                        if await cur.fetchone():
                            continue  # 已经参与过了
                        await cur.execute("INSERT INTO group_choujiang_entries (lottery_id, user_id, entry_data) VALUES (%s, %s, %s)", (lid, user_id, f"report:{chat_id_now}"))
                        logger.info(f"report lottery entry: user={user_id} lottery={lid} keyword={kw}")
                        # 检查是否达到开奖条件
                        await cur.execute("SELECT COUNT(*) FROM group_choujiang_entries WHERE lottery_id=%s", (lid,))
                        cnt = (await cur.fetchone())[0]
                        await cur.execute("SELECT draw_count, winner_count, prize_description, title, type, draw_method, draw_time FROM group_choujiang WHERE id=%s", (lid,))
                        lrow = await cur.fetchone()
                        if lrow and method == "count" and cnt >= draw_cnt_val:
                            # 触发开奖——需要在外面做，这里先标记
                            asyncio.create_task(_auto_draw_from_db(context, lid, l_chat_id))
        except Exception as e:
            logger.error(f"report keyword check err: {e}")

    await_data = _AWAIT_CHOUJIANG_INPUT.get(user_id)
    if not await_data:
        return
    chat_id_str = await_data.get("chat_id", "0")
    chat_id = int(chat_id_str)

    atype = await_data["type"]

    if atype == "create_title":
        await_data["title"] = raw
        await_data["type"] = "create_winners"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
        await message.reply_html(f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>第二步：设置中奖人数</b>\n\n标题：{raw}\n\n请发送中奖人数（数字）：', reply_markup=kb)
        return

    if atype == "create_winners":
        try:
            w = int(raw)
            if w < 1:
                raise ValueError
        except ValueError:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
            await message.reply_html(f"{EMOJI_WARN} 请输入有效的中奖人数（正整数）。", reply_markup=kb)
            return
        await_data["winners"] = w
        method = await_data["method"]
        await_data["type"] = "create_drawval"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
        if method == "count":
            await message.reply_html(f'<tg-emoji emoji-id="{CHART_EMOJI_ID}">📊</tg-emoji> <b>第三步：设置开奖条件</b>\n\n请发送需要参与人数（数字）：', reply_markup=kb)
        else:
            await message.reply_html(f'<tg-emoji emoji-id="{CLOCK_EMOJI_ID}">⏰</tg-emoji> <b>第三步：设置开奖时间</b>\n\n请发送开奖时间，格式 <code>YYYY-MM-DD HH:MM</code>\n示例：<code>2026-12-31 20:00</code>', reply_markup=kb)
        return

    if atype == "create_drawval":
        raw = raw.strip()
        method = await_data["method"]
        if method == "time":
            try:
                datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M")
            except ValueError:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
                await message.reply_html(f"{EMOJI_WARN} 时间格式错误，请使用 YYYY-MM-DD HH:MM", reply_markup=kb)
                return
        else:
            try:
                v = int(raw)
                if v < 1:
                    raise ValueError
            except ValueError:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
                await message.reply_html(f"{EMOJI_WARN} 请输入有效的数字。", reply_markup=kb)
                return
        await_data["draw_value"] = raw
        if await_data["ctype"] == "report":
            await_data["type"] = "create_report_group"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
            await message.reply_html(f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>第四步：设置报道群</b>\n\n请发送目标群的群 ID（在该群发 <code>id</code> 获取）：', reply_markup=kb)
        elif await_data["ctype"] == "points":
            await_data["type"] = "create_cost"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
            await message.reply_html(f'<tg-emoji emoji-id="{STAR_EMOJI_ID}">⭐</tg-emoji> <b>第四步：设置参与积分</b>\n\n请发送每次参与所需的积分数量（数字，0=免费）：', reply_markup=kb)
        else:
            await_data["type"] = "create_confirm"
            await message.reply_html(_format_create_summary(await_data), reply_markup=get_confirm_keyboard(chat_id_str))
        return

    if atype == "create_report_group":
        try:
            gid = int(raw)
        except ValueError:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
            await message.reply_html(f"{EMOJI_WARN} 请输入有效的群 ID（数字）。", reply_markup=kb)
            return
        await_data["report_group_id"] = gid
        # try to get group invite link
        try:
            chat_info = await context.bot.get_chat(gid)
            if chat_info.username:
                await_data["report_group_link"] = f"https://t.me/{chat_info.username}"
            elif chat_info.invite_link:
                await_data["report_group_link"] = chat_info.invite_link
            else:
                link_obj = await context.bot.create_chat_invite_link(gid, member_limit=1)
                await_data["report_group_link"] = link_obj.invite_link
        except Exception:
            await_data["report_group_link"] = ""
        await_data["type"] = "create_report_keyword"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
        link_hint = f"\n链接：{await_data['report_group_link']}" if await_data.get("report_group_link") else ""
        await message.reply_html(f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> <b>第五步：设置报道关键词</b>\n\n报道群：{gid}{link_hint}\n\n请发送报道关键词（用户在该群发送此词即参与）：', reply_markup=kb)
        return

    if atype == "create_report_keyword":
        await_data["report_keyword"] = raw
        await_data["type"] = "create_confirm"
        await message.reply_html(_format_create_summary(await_data), reply_markup=get_confirm_keyboard(chat_id_str))
        return

    if atype == "create_cost":
        try:
            c = int(raw)
            if c < 0:
                raise ValueError
        except ValueError:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data=f"group_choujiang_{chat_id_str}")]])
            await message.reply_html(f"{EMOJI_WARN} 请输入有效的积分数量（0 或正整数）。", reply_markup=kb)
            return
        await_data["cost"] = c
        await_data["type"] = "create_confirm"
        await message.reply_html(_format_create_summary(await_data), reply_markup=get_confirm_keyboard(chat_id_str))
        return

    if atype == "create_prize":
        await_data.setdefault("prizes", []).append(raw)
        await_data["type"] = "create_confirm"
        await message.reply_html(_format_create_summary(await_data), reply_markup=get_confirm_keyboard(chat_id_str))
        return


async def _auto_draw_from_db(context, lottery_id: int, chat_id: int):
    """从 DB 获取抽奖信息然后开奖（用于报道抽奖自动触发）"""
    lottery = await get_choujiang_by_id(lottery_id)
    if lottery and lottery["status"] == "active":
        await do_draw(context, lottery, chat_id)


async def do_draw(context, lottery: dict, chat_id: int, target_chat_id: int = None):
    if not lottery or lottery["status"] != "active":
        return
    winner_ids = await draw_winners(lottery["id"])
    cnt = await get_entry_count(lottery["id"])

    # parse prizes
    prizes = []
    try:
        prizes = json.loads(lottery.get("prize_description", "[]"))
    except Exception:
        prizes = []

    # build winner mentions + DM each winner
    winner_mentions = []
    group_title = str(chat_id)
    try:
        chat_obj = await context.bot.get_chat(chat_id)
        group_title = chat_obj.title or str(chat_id)
    except Exception:
        pass

    for i, wid in enumerate(winner_ids):
        # get mention for group announcement
        try:
            member = await context.bot.get_chat_member(chat_id, wid)
            winner_mentions.append(member.user.mention_html())
        except Exception:
            winner_mentions.append(str(wid))

        # DM the winner with prize info
        prize = prizes[i] if i < len(prizes) else (prizes[-1] if prizes else "请联系管理员领取")
        try:
            dm_text = (
                f'<tg-emoji emoji-id="5404573776253825754">🎊</tg-emoji> <b>恭喜中奖！</b>\n\n'
                f'活动：<b>{lottery["title"]}</b>\n'
                f'群组：{group_title}\n\n'
                f'您获得的奖品：<b>{prize}</b>\n\n'
                f'请联系群管理员领取奖品。'
            )
            await context.bot.send_message(chat_id=wid, text=dm_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to DM winner {wid}: {e}")
        await asyncio.sleep(0.5)

    winners_text = "\n".join(f"{i+1}. {m}" for i, m in enumerate(winner_mentions)) if winner_mentions else "无参与者"
    result_text = (
        f'<tg-emoji emoji-id="{CROWN_EMOJI_ID}">👑</tg-emoji> <b>抽奖结果</b>\n\n'
        f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji> {lottery["title"]}\n'
        f'参与人数：{cnt}\n\n'
        f'<b>中奖名单：</b>\n{winners_text}'
    )
    send_to = target_chat_id if target_chat_id else chat_id
    msg = await context.bot.send_message(chat_id=send_to, text=result_text, parse_mode="HTML")
    settings = await get_choujiang_settings(chat_id)
    if settings["pin_result"] and target_chat_id is None:
        try:
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=False)
        except Exception:
            pass
    if lottery.get("message_id") and target_chat_id is None:
        try:
            await context.bot.unpin_chat_message(chat_id=chat_id, message_id=lottery["message_id"])
        except Exception:
            pass


async def choujiang_scheduler(context: ContextTypes.DEFAULT_TYPE):
    try:
        active = await get_active_time_lotteries()
        now = datetime.datetime.now()  # draw_time 存储时也使用本地时间，保持一致
        for lottery in active:
            if lottery["draw_time"] and lottery["draw_time"] <= now:
                await do_draw(context, lottery, lottery["chat_id"])
    except Exception as e:
        logger.error(f"choujiang_scheduler err: {e}", exc_info=True)


async def run_choujiang_scheduler(application):
    await asyncio.sleep(20)
    while True:
        try:
            await choujiang_scheduler(application)
        except Exception as e:
            logger.error(f"run_choujiang_scheduler err: {e}", exc_info=True)
        await asyncio.sleep(60)


async def _delete_after(bot, chat_id: int, msg_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
