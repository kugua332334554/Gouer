import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
START_MESSAGE = os.getenv("START_MESSAGE")
TIMEZONE_MESSAGE = os.getenv("TIMEZONE_MESSAGE", "")
LINK = os.getenv("LINK")

ADD_PIDANO = os.getenv("ADD_PIDANO", "")
ADD_QUN = os.getenv("ADD_QUN", "")

DB = os.getenv("DB")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")

if not BOT_TOKEN:
    logger.warning("BOT_TOKEN unset")
if not DB:
    logger.warning("DB unset")
