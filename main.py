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
    group_to_supergroup_handler,
    mute_command,
    unmute_command,
    ban_command,
    unban_command,
    kick_command,
    info_command,
    points_command,
    points_rank_command,
    help_command
)
from auth import new_member_handler, auth_callback_handler, chat_member_update_handler
from welcome import welcome_callback_handler, welcome_input_handler
from jifen import checkin_handler, message_points_handler, points_query_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application):
    await init_db()

def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_handler))

    app.add_handler(CallbackQueryHandler(auth_callback_handler, pattern="^auth_"))

    app.add_handler(CallbackQueryHandler(welcome_callback_handler, pattern="^wel_"))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(ChatMemberHandler(chat_member_update_handler, ChatMemberHandler.CHAT_MEMBER))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))

    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, welcome_input_handler), group=1)

    app.add_handler(MessageHandler(filters.Regex("^签到$"), checkin_handler), group=2)

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_points_handler), group=3)

    app.add_handler(MessageHandler(filters.Regex("^(积分|jf)$"), points_query_handler), group=4)

    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, group_to_supergroup_handler))

    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("points", points_command))
    app.add_handler(CommandHandler("points_rank", points_rank_command))
    app.add_handler(CommandHandler("help", help_command))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
