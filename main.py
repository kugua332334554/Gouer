import logging
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ChatMemberHandler,
    MessageHandler,
    filters
)
from telegram import Update
import config
from database import init_db
from handlers import (
    start_handler, 
    callback_handler, 
    my_chat_member_handler,
    group_to_supergroup_handler
)
from auth import new_member_handler, auth_callback_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application):
    logger.info("db init start...")
    await init_db()
    logger.info("db init done.")

def main():
    logger.info("bot starting...")
    app = ApplicationBuilder().token(config.BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_handler))
    
    # 注册进群验证专属的 Callback 处理器 (以 auth_ 开头)
    app.add_handler(CallbackQueryHandler(auth_callback_handler, pattern="^auth_"))
    # 注册普通的 Callback 处理器
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # 注册新成员进群拦截器
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, group_to_supergroup_handler))
    
    logger.info("polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
