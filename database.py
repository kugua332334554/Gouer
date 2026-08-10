import logging
import datetime
import os
import re
import aiomysql
import config

logger = logging.getLogger(__name__)
db_pool = None

# ── SQL injection prevention ──────────────────────────────────────────
_VALID_COLUMN_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def validate_column_name(col: str) -> str:
    """Validate column name; raises ValueError if invalid (SQL injection defense)."""
    if not _VALID_COLUMN_RE.match(col):
        raise ValueError(f"Invalid column name: {col}")
    return col

def _validate_table_name(name: str) -> str:
    """Validate table name; raises ValueError if invalid."""
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid table name: {name}")
    return name

async def init_db():
    global db_pool
    try:
        db_pool = await aiomysql.create_pool(
            host=config.DB_HOST,
            port=int(config.DB_PORT),
            user=config.DB_USER,
            password=config.DB_PASS,
            db=config.DB,
            autocommit=True
        )
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        timezone VARCHAR(100) DEFAULT 'UTC+8 北京/上海',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS pindao (
                        chat_id BIGINT PRIMARY KEY,
                        title VARCHAR(255),
                        username VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
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
                        verify_penalty VARCHAR(50) DEFAULT 'mute',
                        block_blacklist_join BOOLEAN DEFAULT FALSE
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
                try:
                    await cur.execute("ALTER TABLE users ADD COLUMN language VARCHAR(10) DEFAULT 'zh'")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE users ADD COLUMN bio VARCHAR(255) DEFAULT ''")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_points_settings ADD COLUMN delete_time INT DEFAULT 0")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_settings ADD COLUMN block_blacklist_join BOOLEAN DEFAULT FALSE")
                except Exception:
                    pass
                await cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {_common_table('cluster_blacklist')} (
                        user_id BIGINT PRIMARY KEY,
                        username VARCHAR(255) DEFAULT '',
                        reason VARCHAR(255) DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_points (
                        chat_id BIGINT,
                        user_id BIGINT,
                        points INT DEFAULT 0,
                        PRIMARY KEY (chat_id, user_id)
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_checkin (
                        chat_id BIGINT,
                        user_id BIGINT,
                        last_checkin DATE,
                        streak INT DEFAULT 0,
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
                        content_text TEXT,
                        buttons_text TEXT,
                        media_type VARCHAR(20),
                        media_file_id VARCHAR(255),
                        status BOOLEAN DEFAULT TRUE,
                        last_sent_date DATE,
                        last_sent_at DATETIME,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # 兼容旧表：补加新字段（若已存在则忽略错误）
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
                        join_chats TEXT,
                        name_contains VARCHAR(100) DEFAULT '',
                        bio_contains VARCHAR(255) DEFAULT '',
                        need_photo BOOLEAN DEFAULT FALSE,
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
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN report_group_link VARCHAR(255) DEFAULT ''")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN join_chats TEXT")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN name_contains VARCHAR(100) DEFAULT ''")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN bio_contains VARCHAR(255) DEFAULT ''")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE group_choujiang ADD COLUMN need_photo BOOLEAN DEFAULT FALSE")
                except Exception:
                    pass
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_choujiang_entries (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        lottery_id INT NOT NULL,
                        user_id BIGINT NOT NULL,
                        entry_data VARCHAR(255) DEFAULT '',
                        UNIQUE KEY unique_entry (lottery_id, user_id)
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_choujiang_winners (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        lottery_id INT NOT NULL,
                        user_id BIGINT NOT NULL
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_kuaisufabu (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        creator_id BIGINT NOT NULL,
                        name VARCHAR(255) NOT NULL,
                        keyword VARCHAR(100) NOT NULL,
                        content_text TEXT,
                        buttons_text TEXT,
                        media_type VARCHAR(20),
                        media_file_id VARCHAR(255),
                        status BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                try:
                    await cur.execute("ALTER TABLE group_kuaisufabu CHANGE COLUMN chat_id creator_id BIGINT NOT NULL")
                except Exception:
                    pass
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
                        title BOOLEAN DEFAULT FALSE,
                        join_leave BOOLEAN DEFAULT FALSE
                    )
                """)
                # migrate existing tables
                try:
                    await cur.execute("ALTER TABLE group_autodelete ADD COLUMN join_leave BOOLEAN DEFAULT FALSE")
                except Exception: pass
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
                        sign VARCHAR(64),
                        poem VARCHAR(255),
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
                    CREATE TABLE IF NOT EXISTS bot_tokens (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        owner_id BIGINT NOT NULL,
                        bot_token VARCHAR(255) NOT NULL,
                        bot_username VARCHAR(255) DEFAULT '',
                        db_name VARCHAR(100) DEFAULT '',
                        status VARCHAR(20) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                try:
                    await cur.execute("ALTER TABLE bot_tokens ADD COLUMN db_name VARCHAR(100) DEFAULT ''")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE bot_tokens ADD COLUMN pid INT DEFAULT 0")
                except Exception:
                    pass
                try:
                    await cur.execute("ALTER TABLE bot_tokens ADD COLUMN token_hash VARCHAR(64) DEFAULT ''")
                except Exception:
                    pass
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
                    CREATE TABLE IF NOT EXISTS group_keyword_reply (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        keyword VARCHAR(500) NOT NULL,
                        reply_text TEXT DEFAULT NULL,
                        media_type VARCHAR(20) DEFAULT NULL,
                        media_file_id VARCHAR(255) DEFAULT NULL,
                        buttons_text TEXT DEFAULT NULL,
                        match_mode VARCHAR(20) DEFAULT 'contains',
                        status BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_shop (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        name VARCHAR(200) NOT NULL,
                        description TEXT DEFAULT NULL,
                        points_price INT NOT NULL DEFAULT 0,
                        stock INT DEFAULT -1,
                        media_type VARCHAR(20) DEFAULT NULL,
                        media_file_id VARCHAR(255) DEFAULT NULL,
                        delivery_mode VARCHAR(20) DEFAULT 'manual',
                        card_data TEXT DEFAULT NULL,
                        status BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # migrate: add delivery_mode + card_data columns for existing tables
                try:
                    await cur.execute("ALTER TABLE group_shop ADD COLUMN delivery_mode VARCHAR(20) DEFAULT 'manual'")
                except Exception: pass
                try:
                    await cur.execute("ALTER TABLE group_shop ADD COLUMN card_data TEXT DEFAULT NULL")
                except Exception: pass
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_points_lottery (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        ticket_price INT NOT NULL DEFAULT 10,
                        prize_list TEXT DEFAULT NULL,
                        max_winners INT DEFAULT 1,
                        status VARCHAR(20) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_entries (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        lottery_id INT NOT NULL,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255) DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS group_nsfw (
                        chat_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        penalty VARCHAR(20) DEFAULT 'delete',
                        threshold_val FLOAT DEFAULT 0.8
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
                        penalty VARCHAR(20) DEFAULT 'mute',
                        mute_duration INT DEFAULT 600,
                        warn_delete INT DEFAULT 30
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
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS fortune_draws (
                        user_id BIGINT PRIMARY KEY,
                        last_draw_date DATE NOT NULL
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS chat_admins (
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        PRIMARY KEY (chat_id, user_id),
                        INDEX idx_user_id (user_id)
                    )
                """)
                try:
                    await cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {_common_table('stickers')} (
                            file_id VARCHAR(255) PRIMARY KEY,
                            emoji VARCHAR(10),
                            added_by BIGINT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ) DEFAULT CHARSET=utf8mb4
                    """)
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"db init fail: {e}", exc_info=True)

def _clean_chat_id(chat_id: int) -> str:
    """Convert chat_id to safe table-suffix string (digits only)."""
    clean = str(chat_id).replace("-", "")
    if not clean.isdigit():
        raise ValueError(f"Invalid chat_id for table name: {chat_id}")
    return clean

async def save_user(user_id: int, username: str, first_name: str, last_name: str = "", bio: str = ""):
    try:
        full_name = (first_name or "") + (" " + last_name if last_name else "")
        full_name = full_name.strip()
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO users (user_id, username, first_name, bio)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE username = VALUES(username), first_name = VALUES(first_name), bio = VALUES(bio)
                """, (user_id, username, full_name, bio))
    except Exception as e:
        logger.error(f"save user err: {e}", exc_info=True)

async def get_user_id_by_username(username: str) -> int:
    """按 @username 查找 user_id，用于 /mute /unmute 等命令"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id FROM users WHERE username = %s ORDER BY created_at DESC LIMIT 1", (username,))
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


async def get_user_timezone(user_id: int) -> str:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT timezone FROM users WHERE user_id = %s", (user_id,))
                result = await cur.fetchone()
                return result[0] if result else 'UTC+8 北京/上海'
    except Exception as e:
        logger.error(f"get tz err: {e}", exc_info=True)
        return 'UTC+8 北京/上海'

async def update_user_timezone(user_id: int, timezone: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE users SET timezone = %s WHERE user_id = %s", (timezone, user_id))
    except Exception as e:
        logger.error(f"update tz err: {e}", exc_info=True)

async def register_channel(chat_id: int, title: str, username: str = None):
    clean_id = _clean_chat_id(chat_id)
    table_name = f"pindao_{clean_id}"
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO pindao (chat_id, title, username)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE title = VALUES(title), username = VALUES(username)
                """, (chat_id, title, username))
                await cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS `{_validate_table_name(table_name)}` (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        message_id BIGINT,
                        action VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
    except Exception as e:
        logger.error(f"channel table fail: {e}", exc_info=True)

async def register_supergroup(chat_id: int, title: str, username: str = None, chat_type: str = "supergroup"):
    clean_id = _clean_chat_id(chat_id)
    table_name = f"qunzu_{clean_id}"
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO qunzu (chat_id, title, username, type)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE title = VALUES(title), username = VALUES(username), type = VALUES(type)
                """, (chat_id, title, username, chat_type))
                await cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS `{_validate_table_name(table_name)}` (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT,
                        action VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
    except Exception as e:
        logger.error(f"group table fail: {e}", exc_info=True)

async def get_all_groups():
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, title FROM qunzu")
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"get groups err: {e}", exc_info=True)
        return []

async def get_all_channels():
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id, title FROM pindao")
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"get channels err: {e}", exc_info=True)
        return []


# ── 管理员缓存表（避免每次点群组列表都遍历所有群调 API） ──

async def sync_chat_admins(chat_id: int, bot):
    """拉取群/频道所有管理员，全量同步到 chat_admins 表。"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = []
        for member in admins:
            if member.status in ["creator", "administrator"]:
                admin_ids.append(member.user.id)
        if not admin_ids:
            return
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 先删后插（事务内）
                await cur.execute("DELETE FROM chat_admins WHERE chat_id = %s", (chat_id,))
                await cur.executemany(
                    "INSERT IGNORE INTO chat_admins (chat_id, user_id) VALUES (%s, %s)",
                    [(chat_id, uid) for uid in admin_ids])
        logger.info(f"synced {len(admin_ids)} admins for chat {chat_id}")
    except Exception as e:
        logger.error(f"sync_chat_admins err for {chat_id}: {e}")


async def add_chat_admin(chat_id: int, user_id: int):
    """单个添加管理员记录。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT IGNORE INTO chat_admins (chat_id, user_id) VALUES (%s, %s)",
                    (chat_id, user_id))
    except Exception as e:
        logger.error(f"add_chat_admin err: {e}")


async def remove_chat_admin(chat_id: int, user_id: int):
    """单个移除管理员记录。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM chat_admins WHERE chat_id = %s AND user_id = %s",
                    (chat_id, user_id))
    except Exception as e:
        logger.error(f"remove_chat_admin err: {e}")


async def remove_chat_admins(chat_id: int):
    """移除某个 chat 的所有管理员记录（bot 被踢/退群时调用）。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM chat_admins WHERE chat_id = %s", (chat_id,))
    except Exception as e:
        logger.error(f"remove_chat_admins err: {e}")


async def get_user_admin_groups(user_id: int) -> list:
    """纯查表：返回用户是管理员的群组列表 [(chat_id, title), ...]."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT q.chat_id, q.title FROM qunzu q "
                    "INNER JOIN chat_admins a ON q.chat_id = a.chat_id "
                    "WHERE a.user_id = %s", (user_id,))
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"get_user_admin_groups err: {e}", exc_info=True)
        return []


async def get_user_admin_channels(user_id: int) -> list:
    """纯查表：返回用户是管理员的频道列表 [(chat_id, title), ...]."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT p.chat_id, p.title FROM pindao p "
                    "INNER JOIN chat_admins a ON p.chat_id = a.chat_id "
                    "WHERE a.user_id = %s", (user_id,))
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"get_user_admin_channels err: {e}", exc_info=True)
        return []


async def has_chat_admin_data() -> bool:
    """检查 chat_admins 表是否有数据（用于判断是否需要首次全量同步）。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM chat_admins")
                row = await cur.fetchone()
                return row and row[0] > 0
    except Exception:
        return False


# ── 抽签每日限制 ──

async def check_and_record_fortune_draw(user_id: int) -> bool:
    """检查用户今天是否已抽签，未抽则记录。返回 True=允许, False=已抽过."""
    today = datetime.date.today()
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT last_draw_date FROM fortune_draws WHERE user_id = %s",
                    (user_id,))
                row = await cur.fetchone()
                if row and row[0] == today:
                    return False  # 今天已抽
                await cur.execute(
                    "INSERT INTO fortune_draws (user_id, last_draw_date) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE last_draw_date = VALUES(last_draw_date)",
                    (user_id, today))
                return True
    except Exception as e:
        logger.error(f"check_and_record_fortune_draw err: {e}")
        return True  # 异常放行，避免阻塞

# ── 公用数据库 (common DB) ────────────────────────────────────────────
# 主 Bot 与克隆子 Bot 共享一个公用数据库(主库), 共同记录贴纸库(stickers)
# 与外挂黑名单(cluster_blacklist)。子 Bot 通过环境变量 COMMON_DB 拿到主库名。
def _common_table(table: str) -> str:
    """返回公用数据库中共享表的可执行表名。

    与自身 config.DB 不同时(子 Bot)用全限定表名 `{COMMON_DB}`.{table} 跨库读写;
    主 Bot(COMMON_DB==config.DB)直接读本地表。同一 MySQL 实例内跨库访问可用。
    """
    common_db = os.getenv("COMMON_DB") or config.DB
    if common_db and common_db != config.DB:
        _validate_table_name(common_db)
        return f"`{common_db}`.{table}"
    return table


async def add_to_cluster_blacklist(user_id: int, username: str = "", reason: str = "") -> bool:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"""
                    INSERT INTO {_common_table("cluster_blacklist")} (user_id, username, reason)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE username=VALUES(username), reason=VALUES(reason)
                """, (user_id, username, reason))
        return True
    except Exception as e:
        logger.error(f"add_to_cluster_blacklist err: {e}", exc_info=True)
        return False


async def is_cluster_blacklisted(user_id: int) -> bool:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT 1 FROM {_common_table('cluster_blacklist')} WHERE user_id = %s LIMIT 1", (user_id,))
                return cur.rowcount > 0
    except Exception as e:
        logger.error(f"is_cluster_blacklisted err: {e}", exc_info=True)
        return False


async def remove_from_cluster_blacklist(user_id: int) -> bool:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"DELETE FROM {_common_table('cluster_blacklist')} WHERE user_id = %s", (user_id,))
        return True
    except Exception as e:
        logger.error(f"remove_from_cluster_blacklist err: {e}", exc_info=True)
        return False


async def get_verify_settings(chat_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT verify_status, verify_mode, verify_duration, verify_penalty, block_blacklist_join FROM group_settings WHERE chat_id = %s", (chat_id,))
                result = await cur.fetchone()
                if result:
                    return {"status": bool(result[0]), "mode": result[1], "duration": result[2], "penalty": result[3], "block_blacklist": bool(result[4])}
    except Exception as e:
        logger.error(f"get_verify_settings err: {e}", exc_info=True)
    return {"status": False, "mode": "button", "duration": 1, "penalty": "mute", "block_blacklist": False}

async def update_verify_settings(chat_id: int, status: bool, mode: str, duration: int, penalty: str, block_blacklist: bool = False):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO group_settings (chat_id, verify_status, verify_mode, verify_duration, verify_penalty, block_blacklist_join)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE verify_status=VALUES(verify_status), verify_mode=VALUES(verify_mode), verify_duration=VALUES(verify_duration), verify_penalty=VALUES(verify_penalty), block_blacklist_join=VALUES(block_blacklist_join)
                """, (chat_id, status, mode, duration, penalty, block_blacklist))
    except Exception as e:
        logger.error(f"update_verify_settings err: {e}", exc_info=True)

async def get_welcome_settings(chat_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status, delete_time, delete_last, media_type, media_file_id, buttons_text, welcome_text, last_msg_id FROM group_welcome WHERE chat_id = %s", (chat_id,))
                res = await cur.fetchone()
                if res:
                    return {
                        "status": bool(res[0]),
                        "delete_time": res[1],
                        "delete_last": bool(res[2]),
                        "media_type": res[3],
                        "media_file_id": res[4],
                        "buttons_text": res[5],
                        "welcome_text": res[6] or "欢迎 {MENTION} 加入本群",
                        "last_msg_id": res[7]
                    }
    except Exception as e:
        logger.error(f"get_welcome_settings err: {e}", exc_info=True)
    return {
        "status": False,
        "delete_time": 0,
        "delete_last": False,
        "media_type": None,
        "media_file_id": None,
        "buttons_text": None,
        "welcome_text": "欢迎 {MENTION} 加入本群",
        "last_msg_id": None
    }

async def update_welcome_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT IGNORE INTO group_welcome (chat_id) VALUES (%s)",
                    (chat_id,)
                )
                set_parts = []
                values = []
                for k, v in kwargs.items():
                    set_parts.append(f"{validate_column_name(k)}=%s")
                    values.append(v)
                values.append(chat_id)
                sql = f"UPDATE group_welcome SET {', '.join(set_parts)} WHERE chat_id = %s"
                await cur.execute(sql, values)
    except Exception as e:
        logger.error(f"update_welcome_settings err: {e}", exc_info=True)

async def get_points_settings(chat_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status, msg_points, ignore_stickers, delete_time FROM group_points_settings WHERE chat_id = %s", (chat_id,))
                res = await cur.fetchone()
                if res:
                    return {"status": bool(res[0]), "msg_points": res[1], "ignore_stickers": bool(res[2]), "delete_time": res[3]}
    except Exception as e:
        pass
    return {"status": False, "msg_points": 0, "ignore_stickers": True, "delete_time": 0}

async def update_points_settings(chat_id: int, status: bool, msg_points: int, ignore_stickers: bool, delete_time: int):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO group_points_settings (chat_id, status, msg_points, ignore_stickers, delete_time)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE status=VALUES(status), msg_points=VALUES(msg_points), ignore_stickers=VALUES(ignore_stickers), delete_time=VALUES(delete_time)
                """, (chat_id, status, msg_points, ignore_stickers, delete_time))
    except Exception as e:
        logger.error(f"update_points_settings err: {e}", exc_info=True)

async def add_user_points(chat_id: int, user_id: int, points: int):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO user_points (chat_id, user_id, points)
                    VALUES (%s, %s, GREATEST(0, %s))
                    ON DUPLICATE KEY UPDATE points = GREATEST(0, points + %s)
                """, (chat_id, user_id, points, points))
    except Exception as e:
        pass

async def process_checkin(chat_id: int, user_id: int, tz_offset: int = 0) -> dict:
    now_utc = datetime.datetime.utcnow()
    today_local = (now_utc + datetime.timedelta(hours=tz_offset)).date()
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 开启事务 + 行级排他锁，防止并发签到导致双倍积分
                await cur.execute("BEGIN")
                try:
                    await cur.execute(
                        "SELECT last_checkin, streak FROM user_checkin WHERE chat_id=%s AND user_id=%s FOR UPDATE",
                        (chat_id, user_id))
                    row = await cur.fetchone()
                    streak = 0
                    last_checkin_local = None
                    if row:
                        last_checkin_local = row[0]  # 直接是本地日期，无需转换
                        streak = row[1]
                    if last_checkin_local == today_local:
                        await cur.execute("COMMIT")
                        return {"already_checked_in": True}
                    if last_checkin_local == today_local - datetime.timedelta(days=1):
                        streak += 1
                    else:
                        streak = 1
                    gained = streak
                    await cur.execute("""
                        INSERT INTO user_checkin (chat_id, user_id, last_checkin, streak)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE last_checkin=VALUES(last_checkin), streak=VALUES(streak)
                    """, (chat_id, user_id, today_local, streak))
                    await cur.execute("""
                        INSERT INTO user_points (chat_id, user_id, points)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE points = points + %s
                    """, (chat_id, user_id, gained, gained))
                    await cur.execute("SELECT points FROM user_points WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
                    total = (await cur.fetchone())[0]
                    await cur.execute("COMMIT")
                    return {"already_checked_in": False, "gained": gained, "streak": streak, "total": total}
                except Exception:
                    await cur.execute("ROLLBACK")
                    raise
    except Exception as e:
        return {"already_checked_in": True}

async def get_user_points(chat_id: int, user_id: int) -> int:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT points FROM user_points WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
                result = await cur.fetchone()
                return result[0] if result else 0
    except Exception:
        return 0

async def update_user_points_direct(chat_id: int, user_id: int, delta: int) -> int:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO user_points (chat_id, user_id, points)
                    VALUES (%s, %s, GREATEST(0, %s))
                    ON DUPLICATE KEY UPDATE points = GREATEST(0, points + %s)
                """, (chat_id, user_id, delta, delta))
                await cur.execute("SELECT points FROM user_points WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
                result = await cur.fetchone()
                return result[0] if result else 0
    except Exception:
        return 0

async def get_points_rank(chat_id: int, limit: int = 10) -> list:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT user_id, points FROM user_points
                    WHERE chat_id = %s
                    ORDER BY points DESC
                    LIMIT %s
                """, (chat_id, limit))
                return await cur.fetchall()
    except Exception:
        return []

async def get_all_verify_enabled_groups() -> list:
    """获取所有开启了进群验证的群 ID 列表（用于重启后清理被锁用户）。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT chat_id FROM group_settings WHERE verify_status = TRUE")
                return [r[0] for r in await cur.fetchall()]
    except Exception:
        return []


# ── 验证状态持久化（防止重启后用户被永久禁言） ──

async def save_verification(chat_id: int, user_id: int, msg_id: int, correct_ans: str,
                            duration: int, penalty: str):
    """持久化待验证用户，bot 重启后可恢复。"""
    from datetime import datetime, timedelta
    expires = datetime.now() + timedelta(minutes=duration)
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO pending_verifications (chat_id, user_id, msg_id, correct_ans, expires_at) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE msg_id=VALUES(msg_id), correct_ans=VALUES(correct_ans), "
                    "expires_at=VALUES(expires_at)",
                    (chat_id, user_id, msg_id, correct_ans, expires))
    except Exception as e:
        logger.error(f"save_verification err: {e}")


async def delete_verification(chat_id: int, user_id: int):
    """删除验证记录（用户已验证或超时）。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM pending_verifications WHERE chat_id=%s AND user_id=%s",
                    (chat_id, user_id))
    except Exception as e:
        logger.error(f"delete_verification err: {e}")


async def get_all_pending_verifications() -> list:
    """获取所有未过期的待验证用户记录（用于重启恢复）。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT chat_id, user_id, msg_id, correct_ans, expires_at "
                    "FROM pending_verifications WHERE expires_at > NOW()")
                rows = await cur.fetchall()
                return [{"chat_id": r[0], "user_id": r[1], "msg_id": r[2],
                         "correct_ans": r[3], "expires_at": r[4]} for r in rows]
    except Exception as e:
        logger.error(f"get_all_pending_verifications err: {e}")
        return []


async def log_group_action(chat_id: int, user_id: int, action: str):
    clean_id = _clean_chat_id(chat_id)
    table_name = f"qunzu_{clean_id}"
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"""
                    INSERT INTO `{_validate_table_name(table_name)}` (user_id, action)
                    VALUES (%s, %s)
                """, (user_id, action))
    except Exception as e:
        logger.error(f"log_group_action err: {e}")


async def cleanup_old_action_logs(days: int = 30) -> int:
    """清理超过 days 天的群/频道操作日志(动态表 qunzu_% / pindao_%)。

    这些日志表只增不删, 长期运行会无限膨胀, 由每日定时任务删除旧数据。
    返回删除的总行数。
    """
    deleted_total = 0
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND (table_name LIKE 'qunzu\\_%' OR table_name LIKE 'pindao\\_%')
                """)
                tables = [r[0] for r in await cur.fetchall()]
        for t in tables:
            try:
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            f"DELETE FROM `{_validate_table_name(t)}` WHERE created_at < NOW() - INTERVAL %s DAY",
                            (days,))
                        deleted_total += cur.rowcount
            except Exception as e:
                logger.error(f"cleanup table {t} err: {e}")
        if tables:
            logger.info(f"cleanup_old_action_logs: deleted {deleted_total} rows older than {days}d from {len(tables)} tables")
    except Exception as e:
        logger.error(f"cleanup_old_action_logs err: {e}", exc_info=True)
    return deleted_total


async def cleanup_payment_orders(days: int = 30) -> int:
    """清理超过 days 天的未完成支付订单(status != 'paid'), 保留已支付记录。"""
    deleted = 0
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM payment_orders WHERE status != 'paid' AND created_at < NOW() - INTERVAL %s DAY",
                    (days,))
                deleted = cur.rowcount
        logger.info(f"cleanup_payment_orders: deleted {deleted} unpaid orders older than {days}d")
    except Exception as e:
        logger.error(f"cleanup_payment_orders err: {e}", exc_info=True)
    return deleted


# ── 订阅 ──────────────────────────────────────────

async def check_subscription(chat_id: int, feature: str) -> bool:
    """检查群是否拥有某功能的活跃订阅。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT expires_at FROM group_subscriptions WHERE chat_id=%s AND feature=%s",
                    (chat_id, feature))
                row = await cur.fetchone()
                if row and row[0]:
                    from datetime import datetime
                    return row[0] > datetime.now()
    except Exception as e:
        logger.error(f"check_subscription err: {e}")
    return False


async def activate_subscription(chat_id: int, feature: str, days: int = 30):
    """激活/续费群订阅。已有未过期订阅则从过期日续，否则从当前时间开始。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO group_subscriptions (chat_id, feature, expires_at)
                       VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s DAY))
                       ON DUPLICATE KEY UPDATE
                           expires_at = IF(expires_at > NOW(),
                                           DATE_ADD(expires_at, INTERVAL %s DAY),
                                           DATE_ADD(NOW(), INTERVAL %s DAY))""",
                    (chat_id, feature, days, days, days))
    except Exception as e:
        logger.error(f"activate_subscription err: {e}")


async def save_payment_order(merchant_order_no: str, chat_id: int, user_id: int, feature: str, amount: str, currency: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO payment_orders (merchant_order_no, chat_id, user_id, feature, amount, currency, status)
                       VALUES (%s, %s, %s, %s, %s, %s, 'created')
                       ON DUPLICATE KEY UPDATE status='created'""",
                    (merchant_order_no, chat_id, user_id, feature, amount, currency))
    except Exception as e:
        logger.error(f"save_payment_order err: {e}")


async def update_payment_order(merchant_order_no: str, status: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE payment_orders SET status=%s WHERE merchant_order_no=%s",
                    (status, merchant_order_no))
    except Exception as e:
        logger.error(f"update_payment_order err: {e}")


async def get_payment_order(merchant_order_no: str) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT merchant_order_no, chat_id, user_id, feature, amount, currency, status FROM payment_orders WHERE merchant_order_no=%s",
                    (merchant_order_no,))
                row = await cur.fetchone()
                if row:
                    return {"merchant_order_no": row[0], "chat_id": row[1], "user_id": row[2],
                            "feature": row[3], "amount": row[4], "currency": row[5], "status": row[6]}
    except Exception as e:
        logger.error(f"get_payment_order err: {e}")
    return None


# ── Bot 克隆 ──────────────────────────────────────

async def add_bot_token(owner_id: int, bot_token: str, bot_username: str = ""):
    try:
        from crypto_utils import encrypt_token, hash_token
        encrypted = encrypt_token(bot_token)
        token_hash = hash_token(bot_token)
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO bot_tokens (owner_id, bot_token, bot_username, token_hash) VALUES (%s, %s, %s, %s)",
                    (owner_id, encrypted, bot_username, token_hash))
    except Exception as e:
        logger.error(f"add_bot_token err: {e}")


async def get_bot_tokens(owner_id: int) -> list:
    try:
        from crypto_utils import decrypt_token
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, owner_id, bot_token, bot_username, db_name, pid, status, created_at FROM bot_tokens WHERE owner_id=%s ORDER BY id DESC",
                    (owner_id,))
                rows = await cur.fetchall()
                result = []
                for r in rows:
                    try:
                        plain_token = decrypt_token(r[2]) if r[2] else ""
                    except Exception:
                        plain_token = r[2]  # fallback: already plain or corrupt
                    result.append({"id": r[0], "owner_id": r[1], "bot_token": plain_token,
                                   "bot_username": r[3], "db_name": r[4], "pid": r[5],
                                   "status": r[6], "created_at": r[7]})
                return result
    except Exception as e:
        logger.error(f"get_bot_tokens err: {e}")
        return []


async def update_bot_token_db(token_id: int, db_name: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bot_tokens SET db_name=%s WHERE id=%s", (db_name, token_id))
    except Exception as e:
        logger.error(f"update_bot_token_db err: {e}")


async def update_bot_pid(token_id: int, pid: int):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bot_tokens SET pid=%s WHERE id=%s", (pid, token_id))
    except Exception as e:
        logger.error(f"update_bot_pid err: {e}")


async def update_bot_status(token_id: int, status: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bot_tokens SET status=%s WHERE id=%s", (status, token_id))
    except Exception as e:
        logger.error(f"update_bot_status err: {e}")


async def delete_bot_token(token_id: int, owner_id: int):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 先查出 db_name 和 pid
                await cur.execute("SELECT db_name, pid FROM bot_tokens WHERE id=%s AND owner_id=%s", (token_id, owner_id))
                row = await cur.fetchone()
                db_name, pid = row if row else (None, None)

                # 杀掉正在运行的 Bot 进程
                if pid:
                    try:
                        os.kill(pid, 9)
                    except Exception:
                        pass

                # 删除 bot_tokens 记录
                await cur.execute("DELETE FROM bot_tokens WHERE id=%s AND owner_id=%s", (token_id, owner_id))

                # 删除对应的数据库
                if db_name:
                    try:
                        await cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"delete_bot_token err: {e}")


async def is_child_bot(bot_token: str) -> bool:
    """检查 bot token 是否是克隆下级（无克隆和高级版权限）"""
    try:
        from crypto_utils import hash_token
        token_hash = hash_token(bot_token)
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 优先走 token_hash 索引查找（加密后）
                await cur.execute("SELECT bot_token, token_hash FROM bot_tokens WHERE token_hash=%s", (token_hash,))
                row = await cur.fetchone()
                if row:
                    return True
                # 向后兼容：旧数据未加密，直接匹配明文列
                await cur.execute("SELECT id FROM bot_tokens WHERE bot_token=%s AND (token_hash='' OR token_hash IS NULL)", (bot_token,))
                return await cur.fetchone() is not None
    except Exception:
        return False


# ── 贴纸库 ──────────────────────────────────────

async def add_sticker(file_id: str, emoji: str, added_by: int):
    """存贴纸，file_id 唯一，重复则更新 emoji。贴纸库存公用数据库，主/子 Bot 共享。"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"INSERT INTO {_common_table('stickers')} (file_id, emoji, added_by) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE emoji=VALUES(emoji)",
                    (file_id, emoji, added_by))
    except Exception as e:
        logger.error(f"add_sticker err: {e}")


async def get_sticker_by_emoji(emoji: str) -> str:
    """按 emoji 随机取一个贴纸 file_id，找不到返回空"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT file_id FROM {_common_table('stickers')} WHERE emoji=%s ORDER BY RAND() LIMIT 1",
                    (emoji,))
                row = await cur.fetchone()
                return row[0] if row else ""
    except Exception as e:
        logger.error(f"get_sticker_by_emoji err: {e}")
        return ""


async def get_random_sticker() -> str:
    """随机返回一个贴纸 file_id"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT file_id FROM {_common_table('stickers')} ORDER BY RAND() LIMIT 1")
                row = await cur.fetchone()
                return row[0] if row else ""
    except Exception as e:
        logger.error(f"get_random_sticker err: {e}")
        return ""


async def get_all_sticker_emojis() -> list:
    """获取所有已存贴纸的 emoji 列表（去重）"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT DISTINCT emoji FROM {_common_table('stickers')} ORDER BY emoji")
                return [r[0] for r in await cur.fetchall()]
    except Exception as e:
        logger.error(f"get_all_sticker_emojis err: {e}")
        return []


# ── 发言检查 ─────────────────────────────────────

async def get_message_check_settings(chat_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT enabled, require_last_name, require_username, require_photo, "
                    "require_premium, require_channel, channel_username, mute_duration, warn_delete, penalty "
                    "FROM group_message_check WHERE chat_id=%s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {
                        "enabled": bool(row[0]), "require_last_name": bool(row[1]),
                        "require_username": bool(row[2]), "require_photo": bool(row[3]),
                        "require_premium": bool(row[4]), "require_channel": bool(row[5]),
                        "channel_username": row[6] or "", "mute_duration": row[7] or 600,
                        "warn_delete": row[8] or 30, "penalty": row[9] or "mute"
                    }
    except Exception as e:
        logger.error(f"get_message_check_settings err: {e}")
    return {"enabled": False, "require_last_name": False, "require_username": False,
            "require_photo": False, "require_premium": False, "require_channel": False,
            "channel_username": "", "mute_duration": 600, "warn_delete": 30, "penalty": "mute"}


async def update_message_check_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_message_check (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_message_check SET {', '.join(parts)} WHERE chat_id=%s", vals)
    except Exception as e:
        logger.error(f"update_message_check_settings err: {e}")


# ── 开关群 ──────────────────────────────────────

async def get_toggle_settings(chat_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT enabled, open_keyword, open_text, open_media_type, open_media_file_id, "
                    "open_buttons_text, close_keyword, close_text, close_media_type, close_media_file_id, "
                    "close_buttons_text FROM group_toggle WHERE chat_id=%s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    return {
                        "enabled": bool(row[0]), "open_keyword": row[1] or "",
                        "open_text": row[2] or "", "open_media_type": row[3] or "",
                        "open_media_file_id": row[4] or "", "open_buttons_text": row[5] or "",
                        "close_keyword": row[6] or "", "close_text": row[7] or "",
                        "close_media_type": row[8] or "", "close_media_file_id": row[9] or "",
                        "close_buttons_text": row[10] or ""
                    }
    except Exception as e:
        logger.error(f"get_toggle_settings err: {e}")
    return {"enabled": False, "open_keyword": "", "open_text": "", "open_media_type": "",
            "open_media_file_id": "", "open_buttons_text": "", "close_keyword": "",
            "close_text": "", "close_media_type": "", "close_media_file_id": "", "close_buttons_text": ""}


async def update_toggle_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_toggle (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_toggle SET {', '.join(parts)} WHERE chat_id=%s", vals)
    except Exception as e:
        logger.error(f"update_toggle_settings err: {e}")


# ── 反垃圾 ──────────────────────────────────────

async def get_antispam_settings(chat_id: int) -> dict:
    defaults = {"enabled": False, "block_contact": False, "block_location": False,
                "block_channel_send": False, "block_channel_fwd": False, "block_external_ref": False,
                "block_exe": False, "block_mention": False, "block_links": False,
                "block_long_links": False, "block_visitor_bots": False, "block_flood": False,
                "flood_timeout": 10, "flood_count": 5, "penalty": "delete", "mute_duration": 3600,
                "whitelist": "", "warn_delete": 30}
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT enabled, block_contact, block_location, block_channel_send, block_channel_fwd, "
                    "block_external_ref, block_exe, block_mention, block_links, block_long_links, "
                    "block_visitor_bots, block_flood, flood_timeout, flood_count, penalty, mute_duration, whitelist, warn_delete "
                    "FROM group_antispam WHERE chat_id=%s", (chat_id,))
                row = await cur.fetchone()
                if row:
                    keys = list(defaults.keys())
                    return {keys[i]: row[i] if row[i] is not None else defaults[keys[i]] for i in range(len(keys))}
    except Exception as e:
        logger.error(f"get_antispam_settings err: {e}")
    return defaults


async def update_antispam_settings(chat_id: int, **kwargs):
    if not kwargs:
        return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO group_antispam (chat_id) VALUES (%s)", (chat_id,))
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(chat_id)
                await cur.execute(f"UPDATE group_antispam SET {', '.join(parts)} WHERE chat_id=%s", vals)
    except Exception as e:
        logger.error(f"update_antispam_settings err: {e}")


# ── 关键词回复 ──────────────────────────────────────

# ── Points Shop ──────────────────────────────────────

async def get_shop_items(chat_id: int) -> list:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, name, description, points_price, stock, "
                    "media_type, media_file_id, delivery_mode, card_data, status, created_at "
                    "FROM group_shop WHERE chat_id=%s ORDER BY id ASC", (chat_id,))
                rows = await cur.fetchall()
                return [{"id": r[0], "chat_id": r[1], "name": r[2], "description": r[3],
                         "points_price": r[4], "stock": r[5], "media_type": r[6],
                         "media_file_id": r[7], "delivery_mode": r[8], "card_data": r[9],
                         "status": bool(r[10]), "created_at": r[11]} for r in rows]
    except Exception as e:
        logger.error(f"get_shop_items err: {e}")
        return []

async def add_shop_item(chat_id: int, name: str, points_price: int, stock: int = -1,
                         description: str = "") -> int:
    """stock = -1 means unlimited"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO group_shop (chat_id, name, points_price, stock, description) "
                    "VALUES (%s,%s,%s,%s,%s)", (chat_id, name, points_price, stock, description))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"add_shop_item err: {e}")
        return 0

async def update_shop_item(item_id: int, **kwargs):
    if not kwargs: return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
                vals.append(item_id)
                await cur.execute(f"UPDATE group_shop SET {', '.join(parts)} WHERE id=%s", vals)
    except Exception as e:
        logger.error(f"update_shop_item err: {e}")

# ── Card delivery ────────────────────────────────────

async def pop_shop_card(item_id: int) -> str:
    """Pop the first card code from the pool. Returns empty string if none left."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT card_data FROM group_shop WHERE id=%s", (item_id,))
                row = await cur.fetchone()
                if not row or not row[0]:
                    return ""
                cards = row[0].strip().split("\n")
                if not cards or (len(cards) == 1 and not cards[0]):
                    return ""
                first = cards[0].strip()
                remaining = "\n".join(c[0].strip() for c in (cards[1:] if len(cards) > 1 else [""]) if c and c.strip())
                new_stock = len([c for c in remaining.split("\n") if c.strip()]) if remaining else 0
                await cur.execute(
                    "UPDATE group_shop SET card_data=%s, stock=%s, status=%s WHERE id=%s",
                    (remaining, new_stock, new_stock > 0, item_id))
                return first
    except Exception as e:
        logger.error(f"pop_shop_card err: {e}")
        return ""

async def delete_shop_item(item_id: int):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM group_shop WHERE id=%s", (item_id,))
    except Exception as e:
        logger.error(f"delete_shop_item err: {e}")

# ── Points Lottery ───────────────────────────────────

async def get_lotteries(chat_id: int) -> list:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, title, ticket_price, prize_list, "
                    "max_winners, status, created_at FROM group_points_lottery "
                    "WHERE chat_id=%s ORDER BY id DESC", (chat_id,))
                rows = await cur.fetchall()
                return [{"id": r[0], "chat_id": r[1], "title": r[2], "ticket_price": r[3],
                         "prize_list": r[4] or "", "max_winners": r[5], "status": r[6],
                         "created_at": r[7]} for r in rows]
    except Exception as e:
        logger.error(f"get_lotteries err: {e}")
        return []

async def get_lottery(lottery_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, title, ticket_price, prize_list, "
                    "max_winners, status, created_at FROM group_points_lottery WHERE id=%s", (lottery_id,))
                r = await cur.fetchone()
                if r:
                    return {"id": r[0], "chat_id": r[1], "title": r[2], "ticket_price": r[3],
                            "prize_list": r[4] or "", "max_winners": r[5], "status": r[6], "created_at": r[7]}
    except Exception as e:
        logger.error(f"get_lottery err: {e}")
    return None

async def add_lottery(chat_id: int, title: str, ticket_price: int, prize_list: str = "",
                       max_winners: int = 1) -> int:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO group_points_lottery (chat_id, title, ticket_price, prize_list, max_winners) "
                    "VALUES (%s,%s,%s,%s,%s)", (chat_id, title, ticket_price, prize_list, max_winners))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"add_lottery err: {e}")
        return 0

async def update_lottery(lottery_id: int, **kwargs):
    if not kwargs: return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
                vals.append(lottery_id)
                await cur.execute(f"UPDATE group_points_lottery SET {', '.join(parts)} WHERE id=%s", vals)
    except Exception as e:
        logger.error(f"update_lottery err: {e}")

async def delete_lottery(lottery_id: int):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM group_points_lottery WHERE id=%s", (lottery_id,))
                await cur.execute("DELETE FROM lottery_entries WHERE lottery_id=%s", (lottery_id,))
    except Exception as e:
        logger.error(f"delete_lottery err: {e}")

# ── Lottery entries ──────────────────────────────────

async def enter_lottery(lottery_id: int, user_id: int, username: str = "") -> bool:
    """Returns True if entered, False if already entered."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM lottery_entries WHERE lottery_id=%s AND user_id=%s",
                    (lottery_id, user_id))
                if await cur.fetchone():
                    return False  # already entered
                await cur.execute(
                    "INSERT INTO lottery_entries (lottery_id, user_id, username) VALUES (%s,%s,%s)",
                    (lottery_id, user_id, username))
                return True
    except Exception as e:
        logger.error(f"enter_lottery err: {e}")
        return False

async def get_lottery_entries(lottery_id: int) -> list:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT user_id, username FROM lottery_entries WHERE lottery_id=%s", (lottery_id,))
                return [{"user_id": r[0], "username": r[1]} for r in await cur.fetchall()]
    except Exception as e:
        logger.error(f"get_lottery_entries err: {e}")
        return []

async def get_lottery_entry_count(lottery_id: int) -> int:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM lottery_entries WHERE lottery_id=%s", (lottery_id,))
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0

async def get_keyword_replies(chat_id: int) -> list:
    """获取群组的所有关键词回复"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, keyword, reply_text, media_type, media_file_id, "
                    "buttons_text, match_mode, status, created_at "
                    "FROM group_keyword_reply WHERE chat_id=%s ORDER BY id ASC",
                    (chat_id,))
                rows = await cur.fetchall()
                return [
                    {"id": r[0], "chat_id": r[1], "keyword": r[2], "reply_text": r[3],
                     "media_type": r[4], "media_file_id": r[5], "buttons_text": r[6],
                     "match_mode": r[7], "status": bool(r[8]), "created_at": r[9]}
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"get_keyword_replies err: {e}")
        return []


async def get_keyword_reply(reply_id: int) -> dict:
    """获取单条关键词回复"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, chat_id, keyword, reply_text, media_type, media_file_id, "
                    "buttons_text, match_mode, status, created_at "
                    "FROM group_keyword_reply WHERE id=%s", (reply_id,))
                r = await cur.fetchone()
                if r:
                    return {"id": r[0], "chat_id": r[1], "keyword": r[2], "reply_text": r[3],
                            "media_type": r[4], "media_file_id": r[5], "buttons_text": r[6],
                            "match_mode": r[7], "status": bool(r[8]), "created_at": r[9]}
    except Exception as e:
        logger.error(f"get_keyword_reply err: {e}")
    return None


async def add_keyword_reply(chat_id: int, keyword: str, match_mode: str = "contains") -> int:
    """添加关键词回复，返回新 ID"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO group_keyword_reply (chat_id, keyword, match_mode) VALUES (%s,%s,%s)",
                    (chat_id, keyword, match_mode))
                return cur.lastrowid
    except Exception as e:
        logger.error(f"add_keyword_reply err: {e}")
        return 0


async def update_keyword_reply(reply_id: int, **kwargs):
    """更新关键词回复字段"""
    if not kwargs:
        return
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                parts, vals = [], []
                for k, v in kwargs.items():
                    parts.append(f"{validate_column_name(k)}=%s")
                    vals.append(v)
                vals.append(reply_id)
                await cur.execute(
                    f"UPDATE group_keyword_reply SET {', '.join(parts)} WHERE id=%s", vals)
    except Exception as e:
        logger.error(f"update_keyword_reply err: {e}")


async def delete_keyword_reply(reply_id: int):
    """删除关键词回复"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM group_keyword_reply WHERE id=%s", (reply_id,))
    except Exception as e:
        logger.error(f"delete_keyword_reply err: {e}")


async def toggle_keyword_reply(reply_id: int) -> bool:
    """切换关键词回复状态，返回新状态"""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM group_keyword_reply WHERE id=%s", (reply_id,))
                row = await cur.fetchone()
                if row:
                    new_status = not bool(row[0])
                    await cur.execute("UPDATE group_keyword_reply SET status=%s WHERE id=%s",
                                      (new_status, reply_id))
                    return new_status
    except Exception as e:
        logger.error(f"toggle_keyword_reply err: {e}")
    return False
