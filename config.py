import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
LINK = os.getenv("LINK")

from lang import get_template

DB = os.getenv("DB")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
ENCRYPTION_KEY = os.getenv("KEY", "")
PUSH_CHANNEL = os.getenv("PUSH", "")
MYQB_APP_ID = os.getenv("MYQB_APP_ID", "")
MYQB_SECRET = os.getenv("MYQB_SECRET", "")
MYQB_BASE_URL = os.getenv("MYQB_BASE_URL", "https://mch.myqb.io")
AI_PRICE = os.getenv("AI_PRICE", "0.000000")
AI_CURRENCY = os.getenv("AI_CURRENCY", "CNY")
CARD_PRICE = os.getenv("CARD_PRICE", "0.000000")
CARD_CURRENCY = os.getenv("CARD_CURRENCY", "CNY")
if not BOT_TOKEN:
    logger.warning("BOT_TOKEN unset")
if not DB:
    logger.warning("DB unset")
if AI_PRICE != "0" and not MYQB_APP_ID:
    logger.warning("AI_PRICE set but MYQB_APP_ID unset — payment will fail")

_me_cache = None
#getmefun
async def get_me(bot) -> dict:
    global _me_cache
    if _me_cache is None:
        _me_cache = await bot.get_me()
    return _me_cache
