"""
main.py — Entry point for the Alice Is Missing Telegram bot.

Single-instance guard: writes a PID file and kills any previous instance
so there is never a 409 Conflict from two polling loops fighting over
the same Telegram token.
"""

import atexit
import logging
import os
import sys
import fcntl

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

import alice_helpers as helpers
from alice_handlers import (
    cmd_start,
    cmd_help,
    cmd_guide,
    cmd_dev,
    cmd_newgame,
    cmd_join,
    cmd_name,
    cmd_status,
    cmd_hosttools,
    cmd_characterlist,
    cmd_showsus,
    cmd_rename,
    cmd_addsus,
    cmd_fate,
    cmd_seeking_cards,
    cmd_endgame,
    cmd_forcestop,
    cmd_startgame,
    cmd_notes,
    cmd_sus,
    cmd_addnpc,
    cmd_sendguide,
    cmd_sendcharlist,
    cmd_postsus,
    cmd_cancel,
    cmd_message,
    callback_handler,
    message_handler,
    error_handler,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_LOCK_FILE = "/tmp/alice_bot.lock"
_LOCK_HANDLE = None

load_lobby_state = getattr(helpers, "load_lobby_state", lambda: None)

_restore_active_sessions = getattr(helpers, "restore_active_sessions", None)
if _restore_active_sessions is None:
    async def restore_active_sessions(app) -> None:
        return
else:
    restore_active_sessions = _restore_active_sessions


def _acquire_single_instance() -> None:
    """Acquire a non-blocking process lock so only one bot runs at a time."""
    global _LOCK_HANDLE
    _LOCK_HANDLE = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_LOCK_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("Another bot instance is already running. Exiting.")
        sys.exit(1)

    _LOCK_HANDLE.seek(0)
    _LOCK_HANDLE.truncate()
    _LOCK_HANDLE.write(str(os.getpid()))
    _LOCK_HANDLE.flush()
    atexit.register(_release_lock)


def _release_lock() -> None:
    global _LOCK_HANDLE
    if _LOCK_HANDLE is None:
        return
    try:
        fcntl.flock(_LOCK_HANDLE, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        _LOCK_HANDLE.close()
    except OSError:
        pass
    _LOCK_HANDLE = None


def main() -> None:
    _acquire_single_instance()

    # Fix for Python 3.14 asyncio
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Exiting.")
        sys.exit(1)
    load_lobby_state()

    async def _post_init(application: Application) -> None:
        await restore_active_sessions(application)

    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("guide", cmd_guide))
    app.add_handler(CommandHandler("dev", cmd_dev))

    app.add_handler(CommandHandler("newgame", cmd_newgame))
    app.add_handler(CommandHandler("startgame", cmd_startgame))
    app.add_handler(CommandHandler("endgame", cmd_endgame))
    app.add_handler(CommandHandler("forcestop", cmd_forcestop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("hosttools", cmd_hosttools))
    app.add_handler(CommandHandler("characterlist", cmd_characterlist))
    app.add_handler(CommandHandler("showsus", cmd_showsus))

    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("name", cmd_name))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("notes", cmd_notes))
    app.add_handler(CommandHandler("sus", cmd_sus))
    app.add_handler(CommandHandler("addsus", cmd_addsus))
    app.add_handler(CommandHandler("addnpc", cmd_addnpc))
    app.add_handler(CommandHandler("sendguide", cmd_sendguide))
    app.add_handler(CommandHandler("sendcharlist", cmd_sendcharlist))
    app.add_handler(CommandHandler("postsus", cmd_postsus))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("message", cmd_message))
    app.add_handler(CommandHandler("fate", cmd_fate))
    app.add_handler(CommandHandler("seekingcards", cmd_seeking_cards))
    app.add_handler(CommandHandler("seekcards", cmd_seeking_cards))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    logger.info("Alice Is Missing bot is starting…")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
