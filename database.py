import logging
import datetime
import aiomysql
import config

logger = logging.getLogger(__name__)
db_pool = None

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
                try:
                    await cur.execute("ALTER TABLE group_points_settings ADD COLUMN delete_time INT DEFAULT 0")
                except Exception:
                    pass
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
    except Exception as e:
        logger.error(f"db init fail: {e}", exc_info=True)

def _clean_chat_id(chat_id: int) -> str:
    return str(chat_id).replace("-", "")

async def save_user(user_id: int, username: str, first_name: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO users (user_id, username, first_name)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE username = VALUES(username), first_name = VALUES(first_name)
                """, (user_id, username, first_name))
    except Exception as e:
        logger.error(f"save user err: {e}", exc_info=True)

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
                    CREATE TABLE IF NOT EXISTS `{table_name}` (
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
                    CREATE TABLE IF NOT EXISTS `{table_name}` (
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

async def get_verify_settings(chat_id: int) -> dict:
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT verify_status, verify_mode, verify_duration, verify_penalty FROM group_settings WHERE chat_id = %s", (chat_id,))
                result = await cur.fetchone()
                if result:
                    return {"status": bool(result[0]), "mode": result[1], "duration": result[2], "penalty": result[3]}
    except Exception as e:
        logger.error(f"get_verify_settings err: {e}", exc_info=True)
    return {"status": False, "mode": "button", "duration": 1, "penalty": "mute"}

async def update_verify_settings(chat_id: int, status: bool, mode: str, duration: int, penalty: str):
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO group_settings (chat_id, verify_status, verify_mode, verify_duration, verify_penalty)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE verify_status=VALUES(verify_status), verify_mode=VALUES(verify_mode), verify_duration=VALUES(verify_duration), verify_penalty=VALUES(verify_penalty)
                """, (chat_id, status, mode, duration, penalty))
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
                    set_parts.append(f"{k}=%s")
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
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE points = points + %s
                """, (chat_id, user_id, points, points))
    except Exception as e:
        pass

async def process_checkin(chat_id: int, user_id: int, tz_offset: int = 0) -> dict:
    now_utc = datetime.datetime.utcnow()
    today_local = (now_utc + datetime.timedelta(hours=tz_offset)).date()
    today_utc = now_utc.date()
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT last_checkin, streak FROM user_checkin WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
                row = await cur.fetchone()
                streak = 0
                last_checkin_utc = None
                if row:
                    last_checkin_utc = row[0]
                    streak = row[1]
                if last_checkin_utc:
                    last_checkin_local = (datetime.datetime.combine(last_checkin_utc, datetime.time.min) + datetime.timedelta(hours=tz_offset)).date()
                else:
                    last_checkin_local = None
                if last_checkin_local == today_local:
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
                """, (chat_id, user_id, today_utc, streak))
                await cur.execute("""
                    INSERT INTO user_points (chat_id, user_id, points)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE points = points + %s
                """, (chat_id, user_id, gained, gained))
                await cur.execute("SELECT points FROM user_points WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
                total = (await cur.fetchone())[0]
                return {"already_checked_in": False, "gained": gained, "streak": streak, "total": total}
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
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE points = points + %s
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

async def log_group_action(chat_id: int, user_id: int, action: str):
    clean_id = _clean_chat_id(chat_id)
    table_name = f"qunzu_{clean_id}"
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"""
                    INSERT INTO `{table_name}` (user_id, action)
                    VALUES (%s, %s)
                """, (user_id, action))
    except Exception:
        pass
