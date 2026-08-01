import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database
import config

logger = logging.getLogger(__name__)
logger.info("clone module loaded")

_AWAIT_TOKEN = {}
_TOKEN_CACHE = {}  # token → bot_username

# 会员表情
EMOJI_ROBOT = "4927440069725259239"
EMOJI_FOLDER = "5332586662629227075"
EMOJI_DELETE = "6017288111279575194"
EMOJI_PREV = "5875082500023258804"
EMOJI_NEXT = "5875506366050734240"
EMOJI_RESTART = "5260687681733533075"
EMOJI_STOP = "5215273032553078755"
EMOJI_START = "5875506366050734240"

EMOJI_SUCCESS = '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>'
EMOJI_WARN = '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'


def get_clone_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("克隆机器人", callback_data="clone_add", icon_custom_emoji_id=EMOJI_ROBOT)],
        [InlineKeyboardButton("管理克隆机器人", callback_data="clone_list_0", icon_custom_emoji_id=EMOJI_FOLDER)],
        [InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")]
    ])


def get_clone_list_keyboard(bots: list, page: int = 0) -> InlineKeyboardMarkup:
    per_page = 5
    total = max(1, (len(bots) + per_page - 1) // per_page) if bots else 1
    start = page * per_page
    page_bots = bots[start:start + per_page]
    kb = []
    for b in page_bots:
        uname = b.get("bot_username") or "未设置"
        status = b.get("status", "active")
        pid = b.get("pid", 0)
        running = "🟢" if (pid and status == "active") else "🔴"
        label = f"{running} @{uname}"
        kb.append([
            InlineKeyboardButton(label, callback_data=f"clone_info_{b['id']}"),
        ])
        # 控制按钮
        ctrl = []
        if pid and status == "active":
            ctrl.append(InlineKeyboardButton("重启", callback_data=f"clone_restart_{b['id']}", icon_custom_emoji_id=EMOJI_RESTART))
            ctrl.append(InlineKeyboardButton("关闭", callback_data=f"clone_stop_{b['id']}", icon_custom_emoji_id=EMOJI_STOP))
        else:
            ctrl.append(InlineKeyboardButton("开启", callback_data=f"clone_start_{b['id']}", icon_custom_emoji_id=EMOJI_START))
        ctrl.append(InlineKeyboardButton("删除", callback_data=f"clone_del_{b['id']}", icon_custom_emoji_id=EMOJI_DELETE))
        kb.append(ctrl)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"clone_list_{page - 1}", icon_custom_emoji_id=EMOJI_PREV))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total}", callback_data="noop"))
    if (page + 1) * per_page < len(bots):
        nav.append(InlineKeyboardButton("下一页", callback_data=f"clone_list_{page + 1}", icon_custom_emoji_id=EMOJI_NEXT))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("« 返回", callback_data="clone")])
    return InlineKeyboardMarkup(kb)


async def clone_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data

    # ── 主面板 ──
    if data == "clone":
        await query.answer()
        bots = await database.get_bot_tokens(user_id)
        text = (
            f'<tg-emoji emoji-id="{EMOJI_ROBOT}">🤖</tg-emoji> <b>Bot 克隆</b>\n\n'
            f"克隆机器人：提交新 Token，自动创建独立数据库。\n"
            f"管理克隆机器人：查看 / 删除已克隆的下级 Bot。\n\n"
            f"当前已克隆：{len(bots)} 个\n"
            f'{EMOJI_WARN} 下级 Bot 不支持克隆和高级版功能。'
        )
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=get_clone_main_keyboard())
        return

    # ── 克隆机器人：提示输入 Token ──
    if data == "clone_add":
        await query.answer()
        _AWAIT_TOKEN[user_id] = update.effective_chat.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« 取消", callback_data="clone")]])
        await query.message.reply_html(
            f'<tg-emoji emoji-id="{EMOJI_ROBOT}">🤖</tg-emoji> <b>克隆机器人</b>\n\n'
            "请从 @BotFather 获取新 Bot Token，发送给我：\n\n"
            "<i>格式如：123456:ABCdef...</i>\n\n"
            "系统将自动：\n"
            "1️⃣ 验证 Token\n"
            "2️⃣ 创建独立数据库\n"
            "3️⃣ 初始化所有表结构",
            reply_markup=kb
        )
        return

    # ── 管理列表 ──
    if data.startswith("clone_list_"):
        page = int(data.split("_")[-1])
        await query.answer()
        bots = await database.get_bot_tokens(user_id)
        if not bots:
            await query.edit_message_text(
                text=f'<tg-emoji emoji-id="{EMOJI_FOLDER}">📋</tg-emoji> <b>管理克隆机器人</b>\n\n暂无克隆 Bot。',
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data="clone")]])
            )
            return
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{EMOJI_FOLDER}">📋</tg-emoji> <b>管理克隆机器人</b>（共 {len(bots)} 个）',
            parse_mode="HTML",
            reply_markup=get_clone_list_keyboard(bots, page)
        )
        return

    # ── 删除 ──
    if data.startswith("clone_del_"):
        token_id = int(data.split("_")[-1])
        await database.delete_bot_token(token_id, user_id)
        await query.answer("已删除")
        bots = await database.get_bot_tokens(user_id)
        await query.edit_message_text(
            text=f'<tg-emoji emoji-id="{EMOJI_FOLDER}">📋</tg-emoji> <b>管理克隆机器人</b>（共 {len(bots)} 个）',
            parse_mode="HTML",
            reply_markup=get_clone_list_keyboard(bots, 0)
        )
        return

    # ── 重启 ──
    if data.startswith("clone_restart_"):
        token_id = int(data.split("_")[-1])
        bots = await database.get_bot_tokens(user_id)
        bot = next((b for b in bots if b["id"] == token_id), None)
        if bot:
            await _stop_bot_process(bot)
            pid = _launch_bot_process(bot["bot_token"], bot["db_name"])
            await database.update_bot_pid(token_id, pid)
            await database.update_bot_status(token_id, "active")
            await query.answer("✅ 已重启")
        bots = await database.get_bot_tokens(user_id)
        await query.edit_message_text(
            text=f"📋 <b>管理克隆机器人</b>（共 {len(bots)} 个）",
            parse_mode="HTML", reply_markup=get_clone_list_keyboard(bots, 0))
        return

    # ── 关闭 ──
    if data.startswith("clone_stop_"):
        token_id = int(data.split("_")[-1])
        bots = await database.get_bot_tokens(user_id)
        bot = next((b for b in bots if b["id"] == token_id), None)
        if bot:
            await _stop_bot_process(bot)
            await database.update_bot_pid(token_id, 0)
            await database.update_bot_status(token_id, "stopped")
            await query.answer("⏸ 已关闭")
        bots = await database.get_bot_tokens(user_id)
        await query.edit_message_text(
            text=f"📋 <b>管理克隆机器人</b>（共 {len(bots)} 个）",
            parse_mode="HTML", reply_markup=get_clone_list_keyboard(bots, 0))
        return

    # ── 开启 ──
    if data.startswith("clone_start_"):
        token_id = int(data.split("_")[-1])
        bots = await database.get_bot_tokens(user_id)
        bot = next((b for b in bots if b["id"] == token_id), None)
        if bot:
            pid = _launch_bot_process(bot["bot_token"], bot["db_name"])
            await database.update_bot_pid(token_id, pid)
            await database.update_bot_status(token_id, "active")
            await query.answer("▶️ 已开启")
        bots = await database.get_bot_tokens(user_id)
        await query.edit_message_text(
            text=f"📋 <b>管理克隆机器人</b>（共 {len(bots)} 个）",
            parse_mode="HTML", reply_markup=get_clone_list_keyboard(bots, 0))
        return

    # ── 详情 ──
    if data.startswith("clone_info_"):
        token_id = int(data.split("_")[-1])
        bots = await database.get_bot_tokens(user_id)
        bot_info = next((b for b in bots if b["id"] == token_id), None)
        if bot_info:
            token_masked = bot_info["bot_token"][:10] + "..." + bot_info["bot_token"][-5:]
            await query.answer(
                f"Bot: @{bot_info.get('bot_username') or '未设置'}\n"
                f"Token: {token_masked}\n"
                f"数据库: {bot_info.get('db_name') or '未分配'}\n"
                f"状态: {bot_info.get('status')}",
                show_alert=True
            )
        return


# ── 输入处理：接收 Token → 验证 → 建库 → 入库 ──

async def clone_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in _AWAIT_TOKEN:
        return
    # 只消费在发起设置的同一会话里的消息，避免把其他会话的普通发言当成设置输入
    if update.effective_chat is None or update.effective_chat.id != _AWAIT_TOKEN.get(user_id):
        return
    msg = update.message
    if not msg or not msg.text:
        return
    raw = msg.text.strip()
    _AWAIT_TOKEN.pop(user_id, None)

    # 1. 校验 token 格式
    if ":" not in raw or len(raw) < 20:
        await msg.reply_html(f"{EMOJI_WARN} Token 格式不正确。格式如：<code>123456:ABCdef...</code>")
        return

    # 2. 验证 token 可用性（带缓存防 flood control）
    bot_username = _TOKEN_CACHE.get(raw, "")
    if not bot_username:
        try:
            from telegram import Bot
            test_bot = Bot(token=raw)
            me = await test_bot.get_me()
            bot_username = me.username or ""
            await test_bot.close()
            _TOKEN_CACHE[raw] = bot_username
        except Exception as e:
            err_msg = str(e)
            if "Flood" in err_msg or "flood" in err_msg:
                await msg.reply_html(f"{EMOJI_WARN} 请求太频繁，请等几秒再试。")
            else:
                await msg.reply_html(f"{EMOJI_WARN} Token 验证失败：{err_msg}")
            return

    # 3. 入库
    await database.add_bot_token(user_id, raw, bot_username)
    bots = await database.get_bot_tokens(user_id)
    new_bot = bots[0] if bots else None
    if not new_bot:
        await msg.reply_html(f"{EMOJI_WARN} 入库失败，请重试。")
        return

    db_name = f"doge_bot_{new_bot['id']}"

    # 4. 创建独立数据库 + 初始化表结构
    db_ok = await _create_clone_database(db_name)
    if db_ok:
        await database.update_bot_token_db(new_bot["id"], db_name)
    else:
        await msg.reply_html(f"{EMOJI_WARN} 数据库创建失败，但 Token 已保存。请手动创建库 <code>{db_name}</code>")

    # 5. 自动启动克隆 Bot
    pid = _launch_bot_process(raw, db_name)
    await database.update_bot_pid(new_bot["id"], pid)
    logger.info(f"cloned bot launched: @{bot_username} DB={db_name} PID={pid}")

    # 6. 通知用户
    await msg.reply_html(
        f"{EMOJI_SUCCESS} <b>克隆成功！</b>\n\n"
        f"Bot：@{bot_username} 已启动运行\n"
        f"{EMOJI_WARN} 下级 Bot 不支持克隆和高级版。"
    )
    try:
        await msg.delete()
    except Exception:
        pass


# ── 进程管理 ─────────────────────────────────────

def _launch_bot_process(token: str, db_name: str) -> int:
    import subprocess, sys, os as _os
    env = {**_os.environ, "BOT_TOKEN": token, "DB": db_name, "BOT_IS_CHILD": "1"}
    main_py = _os.path.join(_os.path.dirname(__file__), "main.py")
    p = subprocess.Popen(
        [sys.executable, main_py],
        env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    return p.pid


async def _stop_bot_process(bot: dict):
    import os as _os, signal
    pid = bot.get("pid", 0)
    if not pid:
        return
    try:
        _os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    try:
        _os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


# ── 建库 ──────────────────────────────────────────

async def _create_clone_database(db_name: str) -> bool:
    import aiomysql
    try:
        pool = await aiomysql.create_pool(
            host=config.DB_HOST,
            port=int(config.DB_PORT),
            user=config.DB_USER,
            password=config.DB_PASS,
            autocommit=True
        )
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 创建数据库
                from database import _validate_table_name
                safe_name = _validate_table_name(db_name)
                await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{safe_name}` DEFAULT CHARSET=utf8mb4")
                await cur.execute(f"USE `{safe_name}`")

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        timezone VARCHAR(100) DEFAULT 'UTC+8 北京/上海',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("ALTER TABLE users ADD COLUMN language VARCHAR(10) DEFAULT 'zh'")
                await cur.execute("ALTER TABLE users ADD COLUMN bio VARCHAR(255) DEFAULT ''")
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS qunzu (
                        chat_id BIGINT PRIMARY KEY,
                        title VARCHAR(255),
                        username VARCHAR(255),
                        type VARCHAR(50),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_settings (
                        chat_id BIGINT PRIMARY KEY,
                        verify_status BOOLEAN DEFAULT FALSE,
                        verify_mode VARCHAR(50) DEFAULT 'button',
                        verify_duration INT DEFAULT 1,
                        verify_penalty VARCHAR(50) DEFAULT 'mute'
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_welcome (
                        chat_id BIGINT PRIMARY KEY,
                        status BOOLEAN DEFAULT FALSE,
                        delete_time INT DEFAULT 0,
                        delete_last BOOLEAN DEFAULT FALSE,
                        media_type VARCHAR(20) DEFAULT NULL,
                        media_file_id VARCHAR(255) DEFAULT NULL,
                        buttons_text TEXT DEFAULT NULL,
                        welcome_text TEXT DEFAULT NULL,
                        last_msg_id BIGINT DEFAULT NULL
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_points_settings (
                        chat_id BIGINT PRIMARY KEY,
                        status BOOLEAN DEFAULT FALSE,
                        msg_points INT DEFAULT 0,
                        ignore_stickers BOOLEAN DEFAULT TRUE,
                        delete_time INT DEFAULT 0
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_points (
                        chat_id BIGINT, user_id BIGINT,
                        points INT DEFAULT 0,
                        PRIMARY KEY (chat_id, user_id)
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_checkin (
                        chat_id BIGINT, user_id BIGINT,
                        last_checkin DATE, streak INT DEFAULT 0,
                        PRIMARY KEY (chat_id, user_id)
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_dingshi (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        schedule_time VARCHAR(5) NOT NULL,
                        schedule_days VARCHAR(50) DEFAULT '*',
                        interval_minutes INT DEFAULT 0,
                        content_text TEXT, buttons_text TEXT,
                        media_type VARCHAR(20), media_file_id VARCHAR(255),
                        status BOOLEAN DEFAULT TRUE,
                        last_sent_date DATE,
                        last_sent_at DATETIME,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                try:
                    await cur.execute("ALTER TABLE group_dingshi ADD COLUMN interval_minutes INT DEFAULT 0")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_dingshi ADD COLUMN last_sent_at DATETIME")
                except Exception:
                    pass
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_night (
                        chat_id BIGINT PRIMARY KEY,
                        status BOOLEAN DEFAULT FALSE,
                        start_hour INT DEFAULT 0,
                        end_hour INT DEFAULT 6,
                        notify BOOLEAN DEFAULT TRUE
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_choujiang_settings (
                        chat_id BIGINT PRIMARY KEY,
                        pin_lottery BOOLEAN DEFAULT TRUE,
                        pin_result BOOLEAN DEFAULT TRUE,
                        delete_entry INT DEFAULT 0,
                        push_channel VARCHAR(255) DEFAULT '',
                        push_enabled BOOLEAN DEFAULT FALSE
                    )
                """)
                try:
                    await cur.execute("ALTER TABLE group_choujiang_settings ADD COLUMN push_enabled BOOLEAN DEFAULT FALSE")
                except Exception:
                    pass
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_choujiang (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        creator_id BIGINT,
                        type VARCHAR(20) DEFAULT 'general',
                        title VARCHAR(255) NOT NULL,
                        prize_description TEXT,
                        winner_count INT DEFAULT 1,
                        entry_cost INT DEFAULT 0,
                        draw_method VARCHAR(20) DEFAULT 'count',
                        draw_count INT DEFAULT 0,
                        draw_time DATETIME,
                        report_group_id BIGINT DEFAULT 0,
                        report_keyword VARCHAR(100) DEFAULT '',
                        status VARCHAR(20) DEFAULT 'active',
                        message_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN report_group_id BIGINT DEFAULT 0")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN report_keyword VARCHAR(100) DEFAULT ''")
                except Exception:
                    pass
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_choujiang_entries (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        lottery_id INT NOT NULL, user_id BIGINT NOT NULL,
                        entry_data VARCHAR(255) DEFAULT '',
                        UNIQUE KEY (lottery_id, user_id)
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_choujiang_winners (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        lottery_id INT NOT NULL, user_id BIGINT NOT NULL
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_kuaisufabu (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        creator_id BIGINT NOT NULL,
                        name VARCHAR(255) NOT NULL,
                        keyword VARCHAR(100) NOT NULL,
                        content_text TEXT, buttons_text TEXT,
                        media_type VARCHAR(20), media_file_id VARCHAR(255),
                        status BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS card_users (
                        user_id BIGINT PRIMARY KEY,
                        card_type VARCHAR(32) NOT NULL DEFAULT 'normal',
                        bio VARCHAR(255) DEFAULT ''
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_ai (
                        chat_id BIGINT PRIMARY KEY,
                        chat_enabled BOOLEAN DEFAULT FALSE,
                        chat_prompt TEXT,
                        chat_trigger VARCHAR(100) DEFAULT '',
                        audit_enabled BOOLEAN DEFAULT FALSE,
                        audit_penalty VARCHAR(20) DEFAULT 'delete'
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_card (
                        chat_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        template VARCHAR(20) DEFAULT 'default'
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_autodelete (
                        chat_id BIGINT PRIMARY KEY,
                        pin BOOLEAN DEFAULT FALSE,
                        photo BOOLEAN DEFAULT FALSE,
                        title BOOLEAN DEFAULT FALSE
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_permission (
                        chat_id BIGINT PRIMARY KEY,
                        permissions VARCHAR(255) DEFAULT 'all'
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS channel_autobutton (
                        chat_id BIGINT PRIMARY KEY,
                        status BOOLEAN DEFAULT FALSE,
                        buttons_text TEXT
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_weijinci (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        word VARCHAR(255) NOT NULL,
                        penalty VARCHAR(20) DEFAULT 'delete',
                        mute_duration INT DEFAULT 3600,
                        status BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_kv (
                        `key` VARCHAR(191) PRIMARY KEY,
                        value MEDIUMTEXT
                    ) DEFAULT CHARSET=utf8mb4
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS fortunes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        sign VARCHAR(64), poem VARCHAR(255),
                        reading VARCHAR(255),
                        poem_key VARCHAR(191) UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) DEFAULT CHARSET=utf8mb4
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_subscriptions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        feature VARCHAR(32) NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_chat_feature (chat_id, feature)
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS payment_orders (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        merchant_order_no VARCHAR(100) UNIQUE NOT NULL,
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        feature VARCHAR(32) NOT NULL,
                        amount VARCHAR(20) NOT NULL,
                        currency VARCHAR(10) NOT NULL,
                        status VARCHAR(20) DEFAULT 'created',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS stickers (
                        file_id VARCHAR(255) PRIMARY KEY,
                        emoji VARCHAR(10),
                        added_by BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) DEFAULT CHARSET=utf8mb4
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_antispam (
                        chat_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        block_contact BOOLEAN DEFAULT FALSE,
                        block_location BOOLEAN DEFAULT FALSE,
                        block_channel_send BOOLEAN DEFAULT FALSE,
                        block_channel_fwd BOOLEAN DEFAULT FALSE,
                        block_external_ref BOOLEAN DEFAULT FALSE,
                        block_exe BOOLEAN DEFAULT FALSE,
                        block_mention BOOLEAN DEFAULT FALSE,
                        block_links BOOLEAN DEFAULT FALSE,
                        block_long_links BOOLEAN DEFAULT FALSE,
                        block_visitor_bots BOOLEAN DEFAULT FALSE,
                        block_flood BOOLEAN DEFAULT FALSE,
                        flood_timeout INT DEFAULT 10,
                        flood_count INT DEFAULT 5,
                        penalty VARCHAR(20) DEFAULT 'delete',
                        mute_duration INT DEFAULT 3600,
                        whitelist TEXT,
                        warn_delete INT DEFAULT 30
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_toggle (
                        chat_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        open_keyword VARCHAR(100) DEFAULT '',
                        open_text TEXT DEFAULT NULL,
                        open_media_type VARCHAR(20) DEFAULT NULL,
                        open_media_file_id VARCHAR(255) DEFAULT NULL,
                        open_buttons_text TEXT DEFAULT NULL,
                        close_keyword VARCHAR(100) DEFAULT '',
                        close_text TEXT DEFAULT NULL,
                        close_media_type VARCHAR(20) DEFAULT NULL,
                        close_media_file_id VARCHAR(255) DEFAULT NULL,
                        close_buttons_text TEXT DEFAULT NULL
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_message_check (
                        chat_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        require_last_name BOOLEAN DEFAULT FALSE,
                        require_username BOOLEAN DEFAULT FALSE,
                        require_photo BOOLEAN DEFAULT FALSE,
                        require_premium BOOLEAN DEFAULT FALSE,
                        require_channel BOOLEAN DEFAULT FALSE,
                        channel_username VARCHAR(255) DEFAULT '',
                        mute_duration INT DEFAULT 600,
                        warn_delete INT DEFAULT 30,
                        penalty VARCHAR(20) DEFAULT 'mute'
                    )
                """)
                try:
                    await cur.execute("ALTER TABLE group_message_check ADD COLUMN penalty VARCHAR(20) DEFAULT 'mute'")
                except Exception:
                    pass
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS pending_verifications (
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        msg_id BIGINT DEFAULT 0,
                        correct_ans VARCHAR(100) DEFAULT '',
                        expires_at DATETIME NOT NULL,
                        PRIMARY KEY (chat_id, user_id)
                    )
                """)
        pool.close()
        await pool.wait_closed()
        logger.info(f"clone db created: {safe_name}")
        return True
    except Exception as e:
        logger.error(f"create clone db {db_name} failed: {e}")
        return False
