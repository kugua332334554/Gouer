import logging
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
        logger.info("db init success")
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
        logger.info(f"channel table created: {table_name}")
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
        logger.info(f"group table created: {table_name}")
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
