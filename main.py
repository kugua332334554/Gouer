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
from auth import new_member_handler, auth_callback_handler, chat_member_update_handler
from welcome import welcome_callback_handler, welcome_input_handler

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
    
    app.add_handler(CallbackQueryHandler(auth_callback_handler, pattern="^auth_"))
    
    app.add_handler(CallbackQueryHandler(welcome_callback_handler, pattern="^wel_"))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    
    app.add_handler(ChatMemberHandler(chat_member_update_handler, ChatMemberHandler.CHAT_MEMBER))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))
    
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, welcome_input_handler), group=1)
    
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, group_to_supergroup_handler))
    
    logger.info("polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
