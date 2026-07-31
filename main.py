import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
    MessageHandler,
    InlineQueryHandler,
    filters
)
from telegram import Update, ChatPermissions
import config
from database import init_db
import database
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
from auth import new_member_handler, auth_callback_handler, chat_member_update_handler, chat_join_request_handler
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
import card
import ai
import clone
import speak_check
import toggle_group
import anti_bot
import antispam
import keyword_reply
import shop
import nsfw_detect


async def all_module_input_handler(update, context):
    await autodelete.autodelete_handler(update, context)
    if update.channel_post:
        await autobutton.channel_post_handler(update, context)
        return
    if update.effective_user:
        u = update.effective_user
        from database import save_user
        await save_user(u.id, u.username or "", u.first_name or "", u.last_name or "")
    else:
        return
    if update.message and update.effective_chat.type in ('group', 'supergroup'):
        ab = await anti_bot.check_anti_bot(update, context)
        if ab:
            return
        toggled = await toggle_group.check_toggle_keywords(update, context)
        if toggled:
            return
        kwr_matched = await keyword_reply.kwr_check_handler(update, context)
        if kwr_matched:
            return
        nsfw_blocked = await nsfw_detect.nsfw_check_handler(update, context)
        if nsfw_blocked:
            return
        blocked = await antispam.antispam_check_handler(update, context)
        if blocked:
            return
        warned = await speak_check.check_message(update, context)
        if warned:
            return
        detected = await card.try_card(update.message, context.bot, context)
        if detected:
            return
    await dingshi.dingshi_input_handler(update, context)
    await choujiang.choujiang_input_handler(update, context)
    await kuaisufabu.kuaisufabu_input_handler(update, context)
    await ai.ai_input_handler(update, context)
    await card.card_input_handler(update, context)
    await clone.clone_input_handler(update, context)
    await speak_check.speak_check_input_handler(update, context)
    await toggle_group.toggle_input_handler(update, context)
    await keyword_reply.kwr_input_handler(update, context)
    await shop.shop_input_handler(update, context)
    await antispam.antispam_input_handler(update, context)
    await autobutton.autobutton_input_handler(update, context)
    await weijinci.weijinci_input_handler(update, context)
    if await weijinci.weijinci_check_handler(update, context):
        return
    if await ai.fortune_handler(update, context):
        return
    await ai.ai_message_handler(update, context)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

_child_pids = []  # 子进程 PID 列表


async def post_init(application):
    await init_db()
    asyncio.create_task(dingshi.run_dingshi_scheduler(application))
    asyncio.create_task(night.run_night_scheduler(application))
    asyncio.create_task(choujiang.run_choujiang_scheduler(application))
    # 自动启动所有已克隆的子 Bot
    asyncio.create_task(_auto_start_clones())
    # 重启后恢复：清理被锁定的验证用户 + 恢复未完成的支付轮询
    asyncio.create_task(_cleanup_stuck_verifications(application))
    asyncio.create_task(_recover_pending_payments(application))


async def _auto_start_clones():
    import subprocess, sys, os as _os
    from crypto_utils import decrypt_token
    try:
        # 主进程重启，清空所有旧 PID（旧进程已死）
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bot_tokens SET pid=0")
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, bot_token, db_name FROM bot_tokens WHERE status='active' AND db_name!=''"
                )
                rows = await cur.fetchall()
        main_py = _os.path.join(_os.path.dirname(__file__), "main.py")
        for row in rows:
            token_id, encrypted_token, db_name = row
            try:
                token = decrypt_token(encrypted_token) if encrypted_token else ""
            except Exception:
                # 解密失败则视为明文 token（旧数据未加密 / 密钥变更后的回退）
                token = encrypted_token or ""
                logger.warning(f"Token for bot id={token_id} appears unencrypted, using as plaintext")
            if not token:
                logger.error(f"Empty token for bot id={token_id}, skipping")
                continue
            env = {**_os.environ, "BOT_TOKEN": token, "DB": db_name, "BOT_IS_CHILD": "1"}
            p = subprocess.Popen(
                [sys.executable, main_py],
                env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            _child_pids.append(p.pid)
            await database.update_bot_pid(token_id, p.pid)
            logger.info(f"auto-started child bot id={token_id} pid={p.pid} db={db_name}")
    except Exception as e:
        logger.error(f"auto_start_clones failed: {e}")


async def _kill_all_children():
    """主进程关闭时 kill 所有子进程"""
    import os as _os, signal
    for pid in _child_pids:
        try:
            _os.kill(pid, signal.SIGTERM)
            logger.info(f"stopped child pid={pid}")
        except Exception:
            pass
    # 也从 DB 查一遍确保全部关掉
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT pid FROM bot_tokens WHERE pid>0 AND status='active'")
                for (pid,) in await cur.fetchall():
                    try:
                        _os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
                    try:
                        _os.kill(pid, signal.SIGKILL)
                    except Exception:
                        pass
    except Exception:
        pass


async def _cleanup_stuck_verifications(application):
    from database import delete_verification
    try:
        records = await database.get_all_pending_verifications()
        if not records:
            return
        logger.info(f"Cleaning up {len(records)} verification restrictions after restart...")
        for rec in records:
            chat_id = rec["chat_id"]
            user_id = rec["user_id"]
            try:
                await application.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
                logger.info(f"unrestricted user {user_id} in chat {chat_id} after bot restart")
            except Exception as e:
                logger.error(f"failed to unrestrict user {user_id} in chat {chat_id}: {e}")
            await delete_verification(chat_id, user_id)
        logger.info("Verification cleanup complete")
    except Exception as e:
        logger.error(f"cleanup_stuck_verifications failed: {e}")


async def _recover_pending_payments(application):
    from datetime import datetime, timedelta
    from payment import poll_order
    try:
        async with database.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT merchant_order_no, chat_id, user_id, feature, created_at "
                    "FROM payment_orders WHERE status='created' "
                    "AND created_at > DATE_SUB(NOW(), INTERVAL 20 MINUTE)"
                )
                rows = await cur.fetchall()
        if not rows:
            return
        logger.info(f"Recovering {len(rows)} pending payment polls...")
        for row in rows:
            order_no, chat_id, user_id, feature, created_at = row
            elapsed = (datetime.now() - created_at).total_seconds()
            remaining = max(30, 600 - int(elapsed))  # 原始超时 10 分钟
            asyncio.create_task(
                poll_order(application.bot, chat_id, user_id, order_no, feature, timeout=remaining)
            )
            logger.info(f"recovered payment poll: {order_no} ({remaining}s remaining)")
    except Exception as e:
        logger.error(f"recover_pending_payments failed: {e}")


def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(ChatJoinRequestHandler(chat_join_request_handler))
    app.add_handler(CallbackQueryHandler(auth_callback_handler, pattern="^auth_"))
    app.add_handler(CallbackQueryHandler(welcome_callback_handler, pattern="^wel_"))
    app.add_handler(CallbackQueryHandler(dingshi.dingshi_callback_handler, pattern="^(group_dingshi_|dingshi_)"))
    app.add_handler(CallbackQueryHandler(weijinci.weijinci_callback_handler, pattern="^(group_weijinci_|weijinci_)"))
    app.add_handler(CallbackQueryHandler(night.night_callback_handler, pattern="^(group_night_|night_)"))
    app.add_handler(CallbackQueryHandler(choujiang.choujiang_callback_handler, pattern="^(group_choujiang_|cj_)"))
    app.add_handler(CallbackQueryHandler(kuaisufabu.kuaisufabu_callback_handler, pattern="^(kf_|post_fast$)"))
    app.add_handler(CallbackQueryHandler(anti_bot.anti_bot_callback_handler, pattern="^atb_answer_"))
    app.add_handler(CallbackQueryHandler(anti_bot.anti_bot_ban_handler, pattern="^atb_ban"))
    app.add_handler(CallbackQueryHandler(autobutton.autobutton_callback_handler, pattern="^ab_"))
    app.add_handler(CallbackQueryHandler(permission.permission_callback_handler, pattern="^perm_"))
    app.add_handler(CallbackQueryHandler(autodelete.autodelete_callback_handler, pattern="^ad_"))
    app.add_handler(CallbackQueryHandler(card.card_callback_handler, pattern="^card_"))
    app.add_handler(CallbackQueryHandler(ai.ai_callback_handler, pattern="^ai_"))
    app.add_handler(CallbackQueryHandler(speak_check.speak_check_callback_handler, pattern="^spk_"))
    app.add_handler(CallbackQueryHandler(antispam.antispam_callback_handler, pattern="^as_"))
    app.add_handler(CallbackQueryHandler(toggle_group.toggle_callback_handler, pattern="^tg_"))
    app.add_handler(CallbackQueryHandler(keyword_reply.kwr_callback_handler, pattern="^kwr_"))
    app.add_handler(CallbackQueryHandler(shop.shop_callback_handler, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(nsfw_detect.nsfw_callback_handler, pattern="^nsfw_"))
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
    app.add_handler(CommandHandler("shop", shop.shop_command))
    app.add_handler(CommandHandler("r", ai.r_command))
    app.add_handler(CommandHandler("dl", ai.dl_command))

    async def id_cmd(update, context):
        await update.message.reply_text(f'👤 用户 ID：{update.effective_user.id}\n💬 群组 ID：{update.effective_chat.id}')
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^id$") & filters.ChatType.GROUPS, id_cmd))

    app.add_handler(InlineQueryHandler(kuaisufabu.kuaisufabu_inline_handler))

    # 退出时自动 kill 所有子进程
    import atexit, signal as _signal
    def _cleanup():
        logger.info("🛑 Shutting down children...")
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_kill_all_children())
            else:
                loop.run_until_complete(_kill_all_children())
        except Exception:
            pass
    atexit.register(_cleanup)

    logger.info("🚀 Bot starting (main + auto-starting clones)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
