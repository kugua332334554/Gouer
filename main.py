import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    MessageHandler,
    InlineQueryHandler,
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
import dingshi
import weijinci
import night
import choujiang
import kuaisufabu
import autobutton
import permission
import autodelete


async def all_module_input_handler(update, context):
    await autodelete.autodelete_handler(update, context)
    if update.channel_post:
        await autobutton.channel_post_handler(update, context)
        return
    if not update.effective_user:
        return
    await dingshi.dingshi_input_handler(update, context)
    await choujiang.choujiang_input_handler(update, context)
    await kuaisufabu.kuaisufabu_input_handler(update, context)
    await autobutton.autobutton_input_handler(update, context)
    await weijinci.weijinci_input_handler(update, context)
    await weijinci.weijinci_check_handler(update, context)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application):
    await init_db()
    asyncio.create_task(dingshi.run_dingshi_scheduler(application))
    asyncio.create_task(night.run_night_scheduler(application))
    asyncio.create_task(choujiang.run_choujiang_scheduler(application))

def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_handler))

    app.add_handler(CallbackQueryHandler(auth_callback_handler, pattern="^auth_"))

    app.add_handler(CallbackQueryHandler(welcome_callback_handler, pattern="^wel_"))

    app.add_handler(CallbackQueryHandler(dingshi.dingshi_callback_handler, pattern="^(group_dingshi_|dingshi_)"))

    app.add_handler(CallbackQueryHandler(weijinci.weijinci_callback_handler, pattern="^(group_weijinci_|weijinci_)"))

    app.add_handler(CallbackQueryHandler(night.night_callback_handler, pattern="^(group_night_|night_)"))

    app.add_handler(CallbackQueryHandler(choujiang.choujiang_callback_handler, pattern="^(group_choujiang_|cj_)"))

    app.add_handler(CallbackQueryHandler(kuaisufabu.kuaisufabu_callback_handler, pattern="^(kf_|post_fast$)"))

    app.add_handler(CallbackQueryHandler(autobutton.autobutton_callback_handler, pattern="^ab_"))

    app.add_handler(CallbackQueryHandler(permission.permission_callback_handler, pattern="^perm_"))

    app.add_handler(CallbackQueryHandler(autodelete.autodelete_callback_handler, pattern="^ad_"))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(ChatMemberHandler(chat_member_update_handler, ChatMemberHandler.CHAT_MEMBER))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))

    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, welcome_input_handler), group=1)

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, all_module_input_handler), group=0)

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

    app.add_handler(InlineQueryHandler(kuaisufabu.kuaisufabu_inline_handler))

    app.add_handler(MessageHandler(filters.ALL, autobutton.channel_post_handler))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
