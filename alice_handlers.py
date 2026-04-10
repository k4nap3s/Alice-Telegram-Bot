"""All command handlers, callback handlers, and message routing."""

import asyncio
import random
import logging
import html
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from alice_models import GameSession, PlayerState
from alice_keyboards import (
    get_keyboard, PRIVATE_BUTTON_TEXTS, TOP_LEVEL_BUTTON_TEXTS,
    main_menu_inline, game_menu_inline, host_tools_inline,
    notes_markup, notes_pick_markup,
    sus_award_menu, sus_char_list_markup,
)
import alice_helpers as helpers

games = getattr(helpers, "games", None)
if games is None:
    games = {}
    helpers.games = games

pending_name_for_user = getattr(helpers, "pending_name_for_user", None)
if pending_name_for_user is None:
    pending_name_for_user = {}
    helpers.pending_name_for_user = pending_name_for_user

pending_dm_target = getattr(helpers, "pending_dm_target", None)
if pending_dm_target is None:
    pending_dm_target = {}
    helpers.pending_dm_target = pending_dm_target

pending_dm_anon = getattr(helpers, "pending_dm_anon", None)
if pending_dm_anon is None:
    pending_dm_anon = {}
    helpers.pending_dm_anon = pending_dm_anon

pending_dm_route = getattr(helpers, "pending_dm_route", None)
if pending_dm_route is None:
    pending_dm_route = {}
    helpers.pending_dm_route = pending_dm_route

pending_note = getattr(helpers, "pending_note", None)
if pending_note is None:
    pending_note = {}
    helpers.pending_note = pending_note

pending_npc = getattr(helpers, "pending_npc", None)
if pending_npc is None:
    pending_npc = {}
    helpers.pending_npc = pending_npc

pending_sus_char = getattr(helpers, "pending_sus_char", None)
if pending_sus_char is None:
    pending_sus_char = {}
    helpers.pending_sus_char = pending_sus_char

pending_host_rename = getattr(helpers, "pending_host_rename", None)
if pending_host_rename is None:
    pending_host_rename = {}
    helpers.pending_host_rename = pending_host_rename

dev_mode_users = getattr(helpers, "dev_mode_users", None)
if dev_mode_users is None:
    dev_mode_users = set()
    helpers.dev_mode_users = dev_mode_users

bot_halted: bool = bool(getattr(helpers, "bot_halted", False))
bot_halted_by: int | None = getattr(helpers, "bot_halted_by", None)
helpers.bot_halted = bot_halted
helpers.bot_halted_by = bot_halted_by

def find_session(game_id: str) -> GameSession | None:
    return games.get(game_id)

def find_host_session(uid: int) -> GameSession | None:
    for s in games.values():
        if s.host_id == uid and not s.ended:
            return s
    return None

def find_player_session(uid: int) -> GameSession | None:
    for s in games.values():
        if not s.ended and uid in s.players:
            return s
    for s in games.values():
        if not s.ended and s.host_id == uid:
            return s
    return None

def find_session_by_chat(chat_id: int) -> GameSession | None:
    for s in games.values():
        if s.lobby_chat_id == chat_id and not s.ended:
            return s
    return None

notes_text = getattr(helpers, "notes_text", lambda ps: "📝 <b>Your Notes</b>\n\n(No notes yet.)")
sus_table_text = getattr(helpers, "sus_table_text", lambda s: "(no suspicion points)")
update_group_lobby = getattr(helpers, "update_group_lobby", None)
end_game = getattr(helpers, "end_game", None)
save_lobby_state = getattr(helpers, "save_lobby_state", lambda: None)
game_trigger_scheduler = getattr(helpers, "game_trigger_scheduler", None)
group_reminder_loop = getattr(helpers, "group_reminder_loop", None)
build_lobby_text = getattr(helpers, "_lobby_text", None)
build_lobby_keyboard = getattr(helpers, "_lobby_keyboard", None)

if update_group_lobby is None:
    async def update_group_lobby(bot, s) -> None:
        return

if end_game is None:
    async def end_game(s, bot, reason: str = "host", purge: bool = False) -> None:
        return

if game_trigger_scheduler is None:
    async def game_trigger_scheduler(s, bot) -> None:
        return

if group_reminder_loop is None:
    async def group_reminder_loop(s, bot) -> None:
        return

if build_lobby_text is None:
    def build_lobby_text(s: GameSession) -> str:
        if s.is_lobby():
            real_count = sum(1 for uid in s.players if uid >= 0)
            return (
                f"🎮 <b>Alice Is Missing</b>\n"
                f"<b>Game ID:</b> <code>{s.game_id}</code>\n"
                f"<b>Host:</b> {html.escape(s.host_telegram_name)}\n"
                f"<b>Status:</b> 🏠 Lobby ({real_count} player(s))\n\n"
                f"{s.roster_text()}\n\n"
                f"Tap <b>Join</b> to enter, then DM the bot to set your character name."
            )
        if s.is_active():
            elapsed = int(s.elapsed_minutes())
            remaining = int(s.remaining_minutes())
            return (
                f"🎬 <b>Alice Is Missing — LIVE</b>\n"
                f"<b>Game ID:</b> <code>{s.game_id}</code>\n"
                f"<b>Phase:</b> {s.game_phase().capitalize()} · {elapsed} min elapsed · {remaining} min left\n\n"
                f"{s.roster_text()}\n\n"
                f"The story is unfolding. Stay in character."
            )
        return f"🏁 <b>Game {s.game_id} has ended.</b>"

if build_lobby_keyboard is None:
    def build_lobby_keyboard(s: GameSession):
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📜 Characters", callback_data="char_list"),
                InlineKeyboardButton("🎯 Sus Points", callback_data="sus_show_group"),
            ],
            [
                InlineKeyboardButton("📖 Guide", callback_data="group_guide"),
                InlineKeyboardButton("❓ Help", callback_data="group_help"),
            ],
            [
                InlineKeyboardButton("🔗 Join", callback_data=f"join:{s.game_id}"),
                InlineKeyboardButton("▶️ Start", callback_data="game_start"),
            ],
            [InlineKeyboardButton("🛑 End Game", callback_data="game_end")],
        ])


async def refresh_group_lobby(bot, s: GameSession) -> None:
    """Update the sticky group lobby card from local state."""
    text = build_lobby_text(s)
    markup = build_lobby_keyboard(s)
    try:
        if s.lobby_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=s.lobby_chat_id,
                    message_id=s.lobby_msg_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                return
            except Exception:
                pass
        msg = await bot.send_message(
            chat_id=s.lobby_chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        s.lobby_msg_id = msg.message_id
    except Exception as e:
        logger.warning("Could not refresh group lobby: %s", e)


def _session_for_user(uid: int) -> GameSession | None:
    s = find_player_session(uid)
    if s:
        return s
    for candidate in games.values():
        if candidate.ended:
            continue
        if candidate.host_id == uid or uid in candidate.players:
            return candidate
    return None


def _clear_input_state(uid: int, *, keep: set[str] | None = None) -> None:
    """Drop pending text-input state that would otherwise hijack the next DM."""
    keep = keep or set()
    if "name" not in keep:
        pending_name_for_user.pop(uid, None)
    if "dm" not in keep:
        pending_dm_target.pop(uid, None)
        pending_dm_route.pop(uid, None)
        pending_dm_anon.pop(uid, None)
    if "note" not in keep:
        pending_note.pop(uid, None)
    if "npc" not in keep:
        pending_npc.pop(uid, None)
    if "sus" not in keep:
        pending_sus_char.pop(uid, None)
    if "rename" not in keep:
        pending_host_rename.pop(uid, None)
from content import PLAYER_SECRETS, ORACLE_YES, ORACLE_NO

logger = logging.getLogger(__name__)
UTC = timezone.utc
GUIDE_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "alice_is_missing_guide.png"

DUMMY_PLAYERS = {
    -10001: ("Morgan Lee", "Morgan was the last person to see Alice before she vanished."),
    -10002: ("Riley Chen", "Riley found Alice's phone at the lake but told no one."),
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _generate_game_id() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        gid = "".join(random.choices(chars, k=6))
        if gid not in games:
            return gid


def _guide_text() -> str:
    return (
        "📖 <b>Alice Is Missing — Custom Game Guide</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🎬 The Story Begins</b>\n\n"
        "It is Saturday, the first day of winter break.\n\n"
        "Alice has been missing since Wednesday — three days now. No one has seen her. No one knows where she is.\n\n"
        "You are people who knew Alice. Over the next 90 minutes, through messages alone, you will uncover what happened.\n\n"
        "Or you won’t.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🧠 How This Works</b>\n\n"
        "This is a silent roleplaying game. Everything happens through text.\n\n"
        "Stay in character. If needed, step out using <i>(parentheses)</i>. If something crosses a line, use <b>(X)</b> to remove it.\n\n"
        "There will be silence. That’s part of the game. Let it build tension, or use it to reach out privately.\n\n"
        "Characters never truly meet—if they would, create a reason they don’t.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>👤 Your Character</b>\n\n"
        "Before the game begins, you create someone new.\n\n"
        "Think about how they act, how others see them, and most importantly, who they were to Alice and to everyone else.\n\n"
        "These relationships drive the story.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🔐 Your Secrets</b>\n\n"
        "Every character hides multiple truths:\n\n"
        "A shared secret.\n"
        "A secret involving Alice.\n"
        "A darker secret tied to the crime.\n"
        "And one wild, unpredictable secret.\n\n"
        "You don’t need to reveal everything immediately...\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🕵️ Suspicion</b>\n\n"
        "Accuse other characters. If most players agree, the character is given sus points.\n\n"
        "If said character is mentioned in the story in any way through the deck, the character is given sus points.\n\n"
        "By the end, the most suspected become the main suspects—and one may be chosen randomly as the killer.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🃏 Clues</b>\n\n"
        "Clues guide the story.\n\n"
        "When you receive one, bring it into the narrative and share it. If duplicates appear, reveal them in clockwise order.\n\n"
        "The real truth about Alice won’t come easily. It only appears at the right moment.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🤖 The Bot</b>\n\n"
        "The bot drives the story.\n\n"
        "It may give secrets, send optional prompts, allow private or anonymous messages, and answer questions through <b>Divine Fate</b>.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🔮 Fate & Exploration</b>\n\n"
        "When you explore something uncertain, you rely on fate.\n\n"
        "You may discover something—but before it becomes real, you ask.\n\n"
        "If fate allows it, you connect it to the story. If not, it leads nowhere. You may want to tie a character to it by using the deck.\n\n"
        "Not every path has answers.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🏁 Endings</b>\n\n"
        "What happens depends on what you uncover.\n\n"
        "Low suspicion may mean no crime. Hidden secrets may mean Alice is never found. Wrong accusations may lead you astray. So accuse people carefully.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>⏳ The End</b>\n\n"
        "When time runs out, everything stops.\n\n"
        "You get one final message in character.\n\n"
        "Then it’s over.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>💭 Final Thought</b>\n\n"
        "Trust carefully. Speak intentionally. Use silence.\n\n"
        "Alice is missing.\n\n"
        "What happened to her… is already part of your story."
    )


async def _send_guide_asset(bot, chat_id: int, *, reply_markup=None) -> None:
    """Send the guide image if it is available locally; otherwise fall back to text."""
    if GUIDE_IMAGE_PATH.exists():
        try:
            with GUIDE_IMAGE_PATH.open("rb") as photo:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption="📖 <b>Alice Is Missing — Game Guide</b>",
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return
        except Exception as e:
            logger.warning("Could not send guide image: %s", e)

    await bot.send_message(
        chat_id=chat_id,
        text=_guide_text(),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


def _host_tools_text(s: GameSession | None, menu: str) -> str:
    if menu == "game":
        return (
            "🎮 <b>Game Control</b>\n\n"
            "Start, end, or stop the current game."
        )
    if menu == "sus":
        if not s:
            return "🎯 <b>Suspicion</b>\n\nNo game found."
        return (
            "🎯 <b>Suspicion</b>\n\n"
            f"{sus_table_text(s)}\n\n"
            "Use the buttons below to award points or post the table."
        )
    if menu == "roster":
        return (
            "🧭 <b>Roster</b>\n\n"
            "Rename characters or add NPCs."
        )
    if menu == "info":
        return (
            "📖 <b>Info & Guide</b>\n\n"
            "Send the guide or character list to the group."
        )
    return (
        "🔧 <b>Host Tools</b>\n\n"
        "Pick a category."
    )


def _move_sus_points(s: GameSession, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return
    pts = s.sus_points.pop(old_name, None)
    if not pts:
        return
    if new_name not in s.sus_points:
        s.sus_points[new_name] = pts
        return
    existing = s.sus_points[new_name]
    existing["in_game"] = existing.get("in_game", 0) + pts.get("in_game", 0)
    existing["in_text"] = existing.get("in_text", 0) + pts.get("in_text", 0)


async def _show_main_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE, s: GameSession | None) -> None:
    uid = update.effective_user.id
    text = "🏠 <b>Private DM</b>\n\nUse the buttons below."
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=get_keyboard(s, uid),
    )


async def _show_game_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE, s: GameSession) -> None:
    uid = update.effective_user.id
    await update.effective_message.reply_text(
        "🏠 <b>Private DM</b>\n\nUse the buttons below.",
        parse_mode="HTML",
        reply_markup=get_keyboard(s, uid),
    )


async def _show_host_tools_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    s: GameSession,
    menu: str = "main",
) -> None:
    await update.effective_message.reply_text(
        _host_tools_text(s, menu),
        parse_mode="HTML",
        reply_markup=host_tools_inline(s, menu),
    )


async def _show_host_tools_panel(query, s: GameSession, menu: str = "main", notice: str | None = None) -> None:
    text = _host_tools_text(s, menu)
    if notice:
        text = f"{notice}\n\n{text}"
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=host_tools_inline(s, menu),
    )


async def _show_endgame_confirmation(update: Update, s: GameSession) -> None:
    await update.effective_message.reply_text(
        "🛑 <b>End the game?</b>\n\nThis will reveal secrets and stop the session.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, end the game", callback_data="game_end_confirm_yes"),
                InlineKeyboardButton("Cancel", callback_data="game_end_confirm_cancel"),
            ],
        ]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Character list helpers
# ─────────────────────────────────────────────────────────────────────────────

def _char_list_text(s: GameSession, dev_mode: bool = False, show_name_hint: bool = False) -> str:
    lines = ["📜 <b>Characters</b>\n"]
    i = 1
    for uid, ps in s.players.items():
        if uid < 0 and not dev_mode:
            continue
        if ps.character_name == "Awaiting name":
            lines.append(f"{i}. ⏳ {html.escape(ps.telegram_name)} <i>(setting name…)</i>")
        else:
            crown = " 👑" if uid == s.host_id else ""
            prefix = "🤖" if uid < 0 else "👤"
            lines.append(f"{i}. {prefix} {html.escape(ps.character_name)}{crown}")
        i += 1
    for npc in s.npc_names:
        lines.append(f"{i}. 🎭 {html.escape(npc)}")
        i += 1
    if i == 1:
        lines.append("<i>(no characters yet)</i>")
    if show_name_hint:
        lines.append("")
        lines.append("✏️ <b>To change your name:</b> open DM with the bot and send <code>/name NEW NAME</code>.")
    return "\n".join(lines)


def _char_list_inline(s: GameSession) -> InlineKeyboardMarkup | None:
    """Group character lists are now read-only."""
    return None


def _help_text() -> str:
    return (
        "🕵️ <b>Commands</b>\n\n"
        "<b>Group chat</b>\n"
        "• /newgame — create a lobby\n"
        "• /status — show the game state\n"
        "• /characterlist — show the roster\n"
        "• /showsus — show suspicion points\n\n"
        "<b>Private DM</b>\n"
        "• /start — open or restart the bot DM\n"
        "• /join GAMEID — join a game\n"
        "• /name NAME — set or change your character name\n"
        "• /message — send a DM to another player\n"
        "• /notes — view or edit your notes\n"
        "• /fate — ask the oracle a yes/no question\n"
        "• /cancel — cancel the current pending action\n"
        "• /guide — how to play\n\n"
        "<b>Host only</b>\n"
        "• /startgame — start the game\n"
        "• /endgame — end the game\n"
        "• /forcestop — stop the bot and active sessions\n"
        "• /hosttools — open the host tools panel\n"
        "• /sus — award suspicion points\n"
        "• /addnpc — add an NPC\n"
        "• /sendguide — send the guide to the group\n"
        "• /sendcharlist — send the character list to the group\n"
        "• /postsus — send the suspicion table to the group\n\n"
        "<b>Dev / testing</b>\n"
        "• /dev alice — toggle solo test mode\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    global bot_halted, bot_halted_by

    if bot_halted:
        if bot_halted_by is None or bot_halted_by == uid:
            bot_halted = False
            bot_halted_by = None
            helpers.bot_halted = False
            helpers.bot_halted_by = None
            await update.message.reply_text(
                "🕵️ <b>Alice Is Missing</b>\n\n"
                "The bot has been restarted.\n\n"
                "A silent mystery game for groups.\n\n"
                "Your host creates a game in your group chat with /newgame.\n"
                "Tap <b>Join</b> when the lobby card appears, then set your character name here in DM.\n\n"
                "Type /help for all commands.",
                parse_mode="HTML",
                reply_markup=get_keyboard(None, uid),
            )
            return

        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Ask the host to send /start in DM to restart it.",
            reply_markup=get_keyboard(None, uid),
        )
        return

    s = find_player_session(uid)
    await update.message.reply_text(
        "🕵️ <b>Alice Is Missing</b>\n\n"
        "A silent mystery game for groups.\n\n"
        "Your host creates a game in your group chat with /newgame.\n"
        "Tap <b>Join</b> when the lobby card appears, then set your character name here in DM.\n\n"
        "Type /help for all commands.",
        parse_mode="HTML",
        reply_markup=get_keyboard(s, uid),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    priv = update.effective_chat.type == "private"
    s = find_player_session(uid) if priv else None

    await update.effective_message.reply_text(
        _help_text(),
        parse_mode="HTML",
        reply_markup=get_keyboard(s, uid) if priv else None,
    )


async def cmd_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    priv = update.effective_chat.type == "private"
    s = find_player_session(uid) if priv else None
    await _send_guide_asset(
        context.bot,
        update.effective_chat.id,
        reply_markup=get_keyboard(s, uid) if priv else None,
    )


async def cmd_dev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    priv = update.effective_chat.type == "private"
    if not context.args or context.args[0].lower() != "alice":
        return
    if uid in dev_mode_users:
        dev_mode_users.discard(uid)
        msg = "🔧 Dev mode <b>OFF</b>"
    else:
        dev_mode_users.add(uid)
        msg = (
            "🔧 Dev mode <b>ON</b>\n\n"
            "You can start games solo. Two dummy players will join:\n"
            "• Morgan Lee\n• Riley Chen"
        )
    s = find_player_session(uid)
    await update.effective_message.reply_text(
        msg, parse_mode="HTML",
        reply_markup=get_keyboard(s, uid) if priv else None,
    )


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            parse_mode="HTML",
            reply_markup=get_keyboard(None, user.id),
        )
        return

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "⚠️ Use /newgame in your <b>group chat</b> so everyone can see the lobby and join.",
            parse_mode="HTML",
            reply_markup=get_keyboard(None, user.id),
        )
        return

    existing_group = find_session_by_chat(chat.id)
    if existing_group and not existing_group.ended:
        await update.message.reply_text(
            f"⚠️ This group already has active game <code>{existing_group.game_id}</code>.",
            parse_mode="HTML",
        )
        return

    existing = find_player_session(user.id)
    if existing and not existing.ended:
        await update.message.reply_text(
            f"⚠️ You're already hosting game <code>{existing.game_id}</code>.\n"
            f"End it first with /endgame, then create a new one.",
            parse_mode="HTML",
        )
        return

    session = GameSession(
        game_id=_generate_game_id(),
        host_id=user.id,
        lobby_chat_id=chat.id,
        host_telegram_name=user.first_name or "Host",
    )
    session.players[user.id] = PlayerState(
        telegram_name=user.first_name or "Host",
        telegram_id=user.id,
        username=user.username or "",
        character_name="Awaiting name",
    )
    pending_name_for_user[user.id] = session.game_id
    games[session.game_id] = session
    save_lobby_state()

    await update.message.reply_text(
        f"🎮 <b>Game created!</b>  <code>{session.game_id}</code>\n\n"
        f"The lobby card is below — players tap <b>Join</b> to enter.\n"
        f"Use /startgame here when everyone is ready.\n\n"
        f"<b>Host:</b> {html.escape(user.first_name or 'Host')} — "
        f"check your DMs with the bot to set your character name.",
        parse_mode="HTML",
    )
    await refresh_group_lobby(context.bot, session)
    save_lobby_state()

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"👑 You created game <code>{session.game_id}</code>.\n\n"
                f"Send your <b>character name</b> now to get started.\n"
                f"Other players will join from the group lobby card."
            ),
            parse_mode="HTML",
            reply_markup=get_keyboard(session, user.id),
        )
    except Exception:
        pass

    logger.info("Game %s created by %s (%d)", session.game_id, user.first_name, user.id)


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    priv = update.effective_chat.type == "private"

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            reply_markup=get_keyboard(None, user.id) if priv else None,
        )
        return

    if not context.args:
        s = find_player_session(user.id)
        await update.message.reply_text(
            "🔗 Send: <code>/join GAMEID</code>\nExample: <code>/join CGGBS5</code>",
            parse_mode="HTML",
            reply_markup=get_keyboard(s, user.id) if priv else None,
        )
        return

    game_id = context.args[0].upper().strip()
    await _do_join(user, game_id, context, update.message, priv)


async def cmd_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    priv = update.effective_chat.type == "private"

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            reply_markup=get_keyboard(None, user.id) if priv else None,
        )
        return

    s = _session_for_user(user.id)
    kb = get_keyboard(s, user.id) if priv else None

    if not s or user.id not in s.players:
        await update.message.reply_text("⚠️ You're not in any game yet.", reply_markup=kb)
        return

    if not context.args:
        pending_name_for_user[user.id] = s.game_id
        ps = s.players[user.id]
        cur = ps.character_name
        await update.message.reply_text(
            f"🎭 Send your character name.\n"
            f"Current: <i>{html.escape(cur)}</i>",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    await _apply_name(user, s, " ".join(context.args)[:40], context, update.message, priv)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    priv = update.effective_chat.type == "private"

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            reply_markup=get_keyboard(None, uid) if priv else None,
        )
        return

    s = _session_for_user(uid)
    kb = get_keyboard(s, uid) if priv else None

    if not s:
        await update.message.reply_text("📭 No active game found.", reply_markup=kb)
        return

    if s.is_active():
        state = f"🟢 Active · {s.game_phase()} phase · {int(s.elapsed_minutes())} min elapsed"
    elif s.ended:
        state = "🔴 Ended"
    else:
        state = "🏠 Lobby"

    dev = uid in dev_mode_users and uid == s.host_id
    await update.message.reply_text(
        f"📋 <b>Game Status</b>\n"
        f"<b>ID:</b> <code>{s.game_id}</code>\n"
        f"<b>Status:</b> {state}\n"
        f"<b>Host:</b> {html.escape(s.host_telegram_name)}\n\n"
        f"{s.roster_text(include_dummies=dev)}",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def cmd_hosttools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    priv = update.effective_chat.type == "private"

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            reply_markup=get_keyboard(None, uid) if priv else None,
        )
        return

    s = _session_for_user(uid)
    kb = get_keyboard(s, uid) if priv else None

    if not s:
        await update.message.reply_text("📭 No active game found.", reply_markup=kb)
        return
    if uid != s.host_id:
        await update.message.reply_text("Only the host can use host tools.", reply_markup=kb)
        return

    await _show_host_tools_message(update, context, s, "main")


async def cmd_characterlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    uid = update.effective_user.id
    priv = chat.type == "private"

    s = find_session_by_chat(chat.id) if not priv else _session_for_user(uid)
    kb = get_keyboard(s, uid) if priv else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return

    dev = uid in dev_mode_users and uid == s.host_id
    text = _char_list_text(s, dev_mode=dev)

    if priv:
        await update.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=_character_list_dm_markup(s, uid) or kb,
        )
    else:
        await update.message.reply_text(
            _char_list_text(s, dev_mode=dev, show_name_hint=True), parse_mode="HTML",
            reply_markup=None,
        )


async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    priv = chat.type == "private"
    s = _session_for_user(user.id) if priv else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if priv else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return
    if priv and user.id not in s.players:
        await update.message.reply_text("You're not in this game.", reply_markup=kb)
        return

    if not priv and user.id != s.host_id:
        await update.message.reply_text("Use /rename in a private DM with the bot.", reply_markup=kb)
        return

    _clear_input_state(user.id, keep={"name"})
    await update.message.reply_text(
        "✏️ <b>Rename Character</b>\n\nChoose who to rename.",
        parse_mode="HTML",
        reply_markup=_character_list_dm_markup(s, user.id) or kb,
    )


async def cmd_showsus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    priv = chat.type == "private"
    s = _session_for_user(user.id) if priv else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if priv else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return
    table = sus_table_text(s)
    await update.message.reply_text(
        f"📊 <b>Suspicion Points</b>\n\n{table}",
        parse_mode="HTML", reply_markup=kb,
    )


async def cmd_addsus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_sus(update, context)


async def cmd_fate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    priv = update.effective_chat.type == "private"
    s = _session_for_user(uid)
    kb = get_keyboard(s, uid) if priv else None

    if not s or not s.is_active():
        await update.message.reply_text(
            "🔮 The oracle only speaks during an active game.", reply_markup=kb
        )
        return

    if priv:
        await context.bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)
        await asyncio.sleep(random.uniform(1.5, 2.5))

    answer = random.choice(ORACLE_YES + ORACLE_NO)
    await update.message.reply_text(
        f"🔮 <i>{html.escape(answer)}</i>", parse_mode="HTML", reply_markup=kb,
    )


async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    priv = chat.type == "private"

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            reply_markup=get_keyboard(None, user.id) if priv else None,
        )
        return

    s = _session_for_user(user.id) if priv else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if priv else None

    if not s:
        await update.message.reply_text("You're not hosting any game.", reply_markup=kb)
        return
    if user.id != s.host_id:
        await update.message.reply_text("Only the host can end the game.", reply_markup=kb)
        return
    if s.ended:
        await update.message.reply_text("Game already ended.", reply_markup=kb)
        return

    if priv:
        await _show_endgame_confirmation(update, s)
        return

    await update.message.reply_text(
        "🛑 Ending game…",
        reply_markup=get_keyboard(None, user.id) if priv else None,
    )
    await end_game(s, context.bot, reason="host")


async def cmd_addnpc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    priv = chat.type == "private"
    s = _session_for_user(user.id) if priv else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if priv else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return
    if user.id != s.host_id:
        await update.message.reply_text("Only the host can add NPCs.", reply_markup=kb)
        return

    _clear_input_state(user.id, keep={"npc"})
    pending_npc[user.id] = s.game_id
    npc_list = "\n".join(f"• {n}" for n in s.npc_names) if s.npc_names else "(none yet)"
    await update.message.reply_text(
        f"🎭 <b>Add NPC</b>\n\n{npc_list}\n\nSend an NPC name, or type <code>cancel</code>.",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def cmd_sendguide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    s = _session_for_user(user.id) if chat.type == "private" else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if chat.type == "private" else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return
    if user.id != s.host_id:
        await update.message.reply_text("Only the host can send the guide.", reply_markup=kb)
        return

    await _send_guide_asset(context.bot, s.lobby_chat_id)
    await update.message.reply_text("📖 Guide sent to the group.", reply_markup=kb)


async def cmd_sendcharlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    s = _session_for_user(user.id) if chat.type == "private" else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if chat.type == "private" else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return
    if user.id != s.host_id:
        await update.message.reply_text("Only the host can send the character list.", reply_markup=kb)
        return

    await context.bot.send_message(
        chat_id=s.lobby_chat_id,
        text=_char_list_text(
            s,
            dev_mode=user.id in dev_mode_users and user.id == s.host_id,
            show_name_hint=True,
        ),
        parse_mode="HTML",
    )
    await update.message.reply_text("📜 Character list sent to the group.", reply_markup=kb)


async def cmd_postsus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    s = _session_for_user(user.id) if chat.type == "private" else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if chat.type == "private" else None

    if not s:
        await update.message.reply_text("No game found.", reply_markup=kb)
        return
    if user.id != s.host_id:
        await update.message.reply_text("Only the host can send the suspicion table.", reply_markup=kb)
        return

    await context.bot.send_message(
        chat_id=s.lobby_chat_id,
        text=f"📊 <b>Suspicion Points</b>\n\n{sus_table_text(s)}",
        parse_mode="HTML",
    )
    await update.message.reply_text("📊 Suspicion table sent to the group.", reply_markup=kb)


async def cmd_forcestop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global bot_halted, bot_halted_by
    user = update.effective_user
    chat = update.effective_chat
    priv = chat.type == "private"
    s = _session_for_user(user.id) if priv else find_session_by_chat(chat.id)
    kb = get_keyboard(s, user.id) if priv else None

    host_session = find_host_session(user.id)
    if not host_session:
        await update.message.reply_text("Only the host can force stop the bot.", reply_markup=kb)
        return

    await update.message.reply_text(
        "⛔ Force stopping bot and all active sessions…",
        reply_markup=get_keyboard(None, user.id) if priv else None,
    )

    active_sessions = [gs for gs in list(games.values()) if not gs.ended]
    for gs in active_sessions:
        try:
            await end_game(gs, context.bot, reason="force", purge=True)
        except Exception:
            logger.exception("Failed to force-stop session %s", gs.game_id)

    games.clear()
    save_lobby_state()

    bot_halted = True
    bot_halted_by = user.id
    helpers.bot_halted = True
    helpers.bot_halted_by = user.id

    await update.message.reply_text(
        "⛔ Bot is now stopped.\n"
        "Send /start in DM to restart it.",
        reply_markup=get_keyboard(None, user.id) if priv else None,
    )


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    if bot_halted:
        await update.message.reply_text(
            "⛔ The bot is currently stopped.\n"
            "Use /start in DM to restart it first.",
            reply_markup=get_keyboard(None, user.id) if chat.type == "private" else None,
        )
        return

    if chat.type in ("group", "supergroup"):
        s = find_session_by_chat(chat.id)
    else:
        s = _session_for_user(user.id)

    if not s:
        await update.message.reply_text(
            "No lobby found.",
            reply_markup=get_keyboard(None, user.id) if chat.type == "private" else None,
        )
        return
    if user.id != s.host_id:
        await update.message.reply_text("Only the host can start the game.")
        return

    ok, err = await _start_game_session(s, context)
    if not ok:
        await update.message.reply_text(f"⚠️ {err}")


async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    s = _session_for_user(user.id)

    if not s or not s.is_active():
        await update.message.reply_text(
            "📝 Notes are available once the game starts.",
            reply_markup=get_keyboard(s, user.id),
        )
        return
    if user.id not in s.players:
        await update.message.reply_text("You're not in an active game.", reply_markup=get_keyboard(s, user.id))
        return

    ps = s.players[user.id]
    await update.message.reply_text(
        notes_text(ps), parse_mode="HTML", reply_markup=notes_markup(ps),
    )


async def cmd_sus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    s = _session_for_user(user.id)

    if not s or user.id != s.host_id or not s.is_active():
        await update.message.reply_text(
            "🎯 Sus points are host-only during active games.",
            reply_markup=get_keyboard(s, user.id),
        )
        return

    await update.message.reply_text(
        "🎯 <b>Suspicion Control</b>",
        parse_mode="HTML",
        reply_markup=sus_award_menu(),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    s = _session_for_user(user.id)
    cleared = False
    for store in (
        pending_name_for_user,
        pending_dm_target,
        pending_dm_route,
        pending_dm_anon,
        pending_note,
        pending_npc,
        pending_sus_char,
        pending_host_rename,
    ):
        if user.id in store:
            store.pop(user.id, None)
            cleared = True

    await update.message.reply_text(
        "Cancelled." if cleared else "Nothing to cancel.",
        reply_markup=get_keyboard(s, user.id),
    )


async def cmd_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    s = _session_for_user(user.id)

    if not s or not s.is_active():
        await update.message.reply_text(
            "💬 Messaging works only during active games.",
            reply_markup=get_keyboard(s, user.id),
        )
        return
    if user.id not in s.players:
        await update.message.reply_text("You're not in this game.", reply_markup=get_keyboard(s, user.id))
        return

    await _show_player_pick(user.id, s, update.message, context)


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════════════════


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if bot_halted:
        try:
            await update.callback_query.answer(
                "Bot is stopped. Send /start in DM to restart it.",
                show_alert=True,
            )
        except Exception:
            pass
        return

    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    # DM messaging is a multi-step callback flow, so preserve its pending state
    # until the route/text step finishes or the user cancels it.
    if data.startswith(("dm_pick:", "dm_route:", "dm_anon:", "dm_cancel")):
        _clear_input_state(user_id, keep={"dm"})
    else:
        _clear_input_state(user_id)

    try:
        # ── PRIVATE MENU NAVIGATION ─────────────────────────────────────
        if data in {"menu_main", "menu_back"}:
            s = find_player_session(user_id)
            await query.answer()
            await query.edit_message_text(
                "🏠 <b>Private DM</b>\n\nUse the buttons below.",
                parse_mode="HTML",
                reply_markup=None,
            )
            if s:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🏠 <b>Private DM</b>\n\nUse the buttons below.",
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
            return

        if data == "menu_game":
            s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            if user_id not in s.players:
                await query.answer("You're not in this game.", show_alert=True)
                return
            await query.answer()
            await query.edit_message_text(
                "🏠 <b>Private DM</b>\n\nUse the buttons below.",
                parse_mode="HTML",
                reply_markup=None,
            )
            await context.bot.send_message(
                chat_id=user_id,
                text="🏠 <b>Private DM</b>\n\nUse the buttons below.",
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user_id),
            )
            return

        if data == "menu_host":
            s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            if user_id != s.host_id:
                await query.answer("Host tools are host-only.", show_alert=True)
                return
            await query.answer()
            await _show_host_tools_panel(query, s, "main")
            return

        # ── JOIN ──────────────────────────────────────────────────────────
        if data.startswith("join:"):
            game_id = data.split(":", 1)[1]
            s = find_session(game_id)

            if not s or s.ended or s.started:
                await query.answer("Game not available or already started.", show_alert=True)
                return

            if user_id in s.players:
                if user_id in pending_name_for_user:
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"🎮 You're already in game <code>{game_id}</code>!\n\n"
                                f"Send your <b>character name</b> here to finish joining."
                            ),
                            parse_mode="HTML",
                            reply_markup=get_keyboard(s, user_id),
                        )
                        await query.answer("Check your DMs to set your character name!")
                    except Exception:
                        await query.answer(
                            "You're in! Open a DM with this bot and send your character name.",
                            show_alert=True,
                        )
                else:
                    await query.answer("You're already in this game.", show_alert=True)
                return

            s.players[user_id] = PlayerState(
                telegram_name=update.effective_user.first_name or "Player",
                telegram_id=user_id,
                username=update.effective_user.username or "",
            )
            pending_name_for_user[user_id] = game_id

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🎮 You joined game <code>{game_id}</code>!\n\n"
                        f"Send your <b>character name</b> here to lock your role."
                    ),
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
            except Exception:
                s.players.pop(user_id, None)
                pending_name_for_user.pop(user_id, None)
                await query.answer(
                    "I can't DM you yet.\nOpen a chat with this bot, press Start, then tap Join again.",
                    show_alert=True,
                )
                return

            await refresh_group_lobby(context.bot, s)
            save_lobby_state()
            await query.answer("✅ Joined! Check your DMs to set your character name.")
            return

        # ── START GAME ────────────────────────────────────────────────────
        if data == "game_start":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            if user_id != s.host_id:
                await query.answer("Only the host can start the game.", show_alert=True)
                return

            ok, err = await _start_game_session(s, context)
            await query.answer("🎬 Game started!" if ok else err, show_alert=not ok)
            return

        # ── END GAME ──────────────────────────────────────────────────────
        if data == "game_end":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Only the host can end the game.", show_alert=True)
                return
            if s.ended:
                await query.answer("Game already ended.", show_alert=True)
                return
            if query.message.chat.type == "private":
                await query.answer()
                await query.edit_message_text(
                    "🛑 <b>End the game?</b>\n\nThis will reveal secrets and stop the session.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("Yes, end the game", callback_data="game_end_confirm_yes"),
                            InlineKeyboardButton("Cancel", callback_data="game_end_confirm_cancel"),
                        ],
                    ]),
                )
                return
            await query.answer()
            await end_game(s, context.bot, reason="host")
            return

        # ── LOBBY CLOSE (legacy — kept so old messages don't crash) ───────
        if data == "lobby_close":
            await query.answer()
            return

        # ── CHARACTER LIST (group button) ─────────────────────────────────
        if data == "char_list":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            dev = user_id in dev_mode_users and user_id == s.host_id
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=_char_list_text(s, dev_mode=dev, show_name_hint=True),
                parse_mode="HTML",
                reply_markup=None,
            )
            return

        # ── CHARACTER RENAME MENU (notes-style picker) ────────────────────
        if data == "char_rename_menu":
            # Works from group char-list message or DM
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return

            rows = []
            # Own character — always available
            if user_id in s.players:
                ps = s.players[user_id]
                label = ps.character_name if ps.character_name != "Awaiting name" else ps.telegram_name
                rows.append([InlineKeyboardButton(
                    f"👤 {label[:44]} (you)", callback_data="self_rename"
                )])
            # Host also sees all other players and NPCs
            if user_id == s.host_id:
                for pid, ps in s.players.items():
                    if pid < 0 or pid == user_id:
                        continue
                    label = ps.character_name if ps.character_name != "Awaiting name" else ps.telegram_name
                    rows.append([InlineKeyboardButton(
                        f"👤 {label[:44]}", callback_data=f"host_rename_pick_grp:{pid}"
                    )])
                for idx, npc in enumerate(s.npc_names):
                    rows.append([InlineKeyboardButton(
                        f"🎭 {npc[:46]}", callback_data=f"npc_rename_grp:{idx}"
                    )])

            if not rows:
                await query.answer("No characters to rename.", show_alert=True)
                return

            _clear_input_state(user_id, keep={"name"})
            rows.append([InlineKeyboardButton("↩ Back", callback_data="char_list_back")])
            await query.answer()
            await query.edit_message_text(
                "✏️ <b>Rename Character</b>\n\nWho would you like to rename?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        # ── CHARACTER LIST BACK (from rename menu) ────────────────────────
        if data == "char_list_back":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            dev = user_id in dev_mode_users and user_id == s.host_id
            await query.answer()
            await query.edit_message_text(
                _char_list_text(s, dev_mode=dev, show_name_hint=True),
                parse_mode="HTML",
                reply_markup=None,
            )
            return

        # ── SELF-RENAME ───────────────────────────────────────────────────
        if data == "self_rename":
            s = find_player_session(user_id)
            if not s or s.ended or user_id not in s.players:
                await query.answer("You're not in an active game.", show_alert=True)
                return
            pending_name_for_user[user_id] = s.game_id
            ps = s.players[user_id]
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✏️ <b>Rename your character</b>\n"
                        f"Current: <i>{html.escape(ps.character_name)}</i>\n\n"
                        f"Send your new character name, or type <code>cancel</code>."
                    ),
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
                await query.answer("Check your DMs to enter your new name.")
            except Exception:
                pending_name_for_user.pop(user_id, None)
                await query.answer("Open a DM with this bot first, then try again.", show_alert=True)
            return

        # ── NPC RENAME FROM GROUP ─────────────────────────────────────────
        if data.startswith("npc_rename_grp:"):
            idx = int(data.split(":", 1)[1])
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            if user_id != s.host_id:
                await query.answer("Only the host can rename NPCs.", show_alert=True)
                return
            if idx < 0 or idx >= len(s.npc_names):
                await query.answer("NPC not found.", show_alert=True)
                return
            _clear_input_state(user_id, keep={"rename"})
            pending_host_rename[user_id] = (s.game_id, "npc", str(idx))
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🎭 <b>Rename NPC</b>\n"
                        f"Current: <i>{html.escape(s.npc_names[idx])}</i>\n\n"
                        f"Send the new name, or type <code>cancel</code>."
                    ),
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
                await query.answer("Check your DM to enter the new NPC name.")
            except Exception:
                pending_host_rename.pop(user_id, None)
                await query.answer("Couldn't DM you. Open bot DM first.", show_alert=True)
            return

        # ── ADD NPC FROM GROUP ────────────────────────────────────────────
        if data == "npc_add_grp":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            if user_id != s.host_id:
                await query.answer("Only the host can add NPCs.", show_alert=True)
                return
            _clear_input_state(user_id, keep={"npc"})
            pending_npc[user_id] = s.game_id
            npc_list = "\n".join(f"• {n}" for n in s.npc_names) if s.npc_names else "(none yet)"
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🎭 <b>Add NPC</b>\n\n{npc_list}\n\n"
                        f"Send an NPC name, or type <code>cancel</code>."
                    ),
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
                await query.answer("Check your DM to add an NPC.")
            except Exception:
                pending_npc.pop(user_id, None)
                await query.answer("Couldn't DM you. Open bot DM first.", show_alert=True)
            return

        # ── ADD NPC FROM DM ───────────────────────────────────────────────
        if data == "add_npc_dm":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("No active game.", show_alert=True)
                return
            _clear_input_state(user_id, keep={"npc"})
            pending_npc[user_id] = s.game_id
            npc_list = "\n".join(f"• {n}" for n in s.npc_names) if s.npc_names else "(none yet)"
            await query.answer()
            await query.edit_message_text(
                f"🎭 <b>Add NPC</b>\n\n{npc_list}\n\nSend an NPC name, or type <code>cancel</code>.",
                parse_mode="HTML",
            )
            return

        # ── HOST RENAME PLAYER (from DM char list) ────────────────────────
        if data.startswith("host_rename_pick:"):
            target_uid = int(data.split(":", 1)[1])
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            if target_uid not in s.players:
                await query.answer("Player not found.", show_alert=True)
                return
            _clear_input_state(user_id, keep={"rename"})
            pending_host_rename[user_id] = (s.game_id, "player", str(target_uid))
            target = s.players[target_uid]
            cur = target.character_name if target.character_name != "Awaiting name" else target.telegram_name
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"✏️ Rename <b>{html.escape(target.telegram_name)}</b>\n"
                    f"Current: <i>{html.escape(cur)}</i>\n\n"
                    f"Send the new character name, or type <code>cancel</code>."
                ),
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user_id),
            )
            return

        # ── HOST RENAME NPC (from DM char list) ───────────────────────────
        if data.startswith("host_rename_npc:"):
            idx = int(data.split(":", 1)[1])
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("No game.", show_alert=True)
                return
            if idx < 0 or idx >= len(s.npc_names):
                await query.answer("NPC not found.", show_alert=True)
                return
            _clear_input_state(user_id, keep={"rename"})
            pending_host_rename[user_id] = (s.game_id, "npc", str(idx))
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎭 Rename NPC: <i>{html.escape(s.npc_names[idx])}</i>\n\n"
                    f"Send the new name, or type <code>cancel</code>."
                ),
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user_id),
            )
            return

        # ── HOST RENAME PLAYER (from group char_rename_menu) ──────────────
        if data.startswith("host_rename_pick_grp:"):
            target_uid = int(data.split(":", 1)[1])
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            if target_uid not in s.players:
                await query.answer("Player not found.", show_alert=True)
                return
            _clear_input_state(user_id, keep={"rename"})
            pending_host_rename[user_id] = (s.game_id, "player", str(target_uid))
            target = s.players[target_uid]
            cur = target.character_name if target.character_name != "Awaiting name" else target.telegram_name
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✏️ Rename <b>{html.escape(target.telegram_name)}</b>\n"
                        f"Current: <i>{html.escape(cur)}</i>\n\n"
                        f"Send the new character name, or type <code>cancel</code>."
                    ),
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
                await query.answer("Check your DM.")
            except Exception:
                pending_host_rename.pop(user_id, None)
                await query.answer("Couldn't DM you. Open bot DM first.", show_alert=True)
            return

        # ── PRIVATE GAME MENU ACTIONS ────────────────────────────────────
        if data == "gm_charlist":
            s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text=_char_list_text(s, dev_mode=user_id in dev_mode_users and user_id == s.host_id, show_name_hint=False),
                parse_mode="HTML",
                reply_markup=_character_list_dm_markup(s, user_id),
            )
            return

        if data == "gm_sus_view":
            s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📊 <b>Suspicion Points</b>\n\n{sus_table_text(s)}",
                parse_mode="HTML",
            )
            return

        if data == "gm_notes":
            s = find_player_session(user_id)
            if not s or not s.is_active() or user_id not in s.players:
                await query.answer("Notes are available during an active game.", show_alert=True)
                return
            ps = s.players[user_id]
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text=notes_text(ps),
                parse_mode="HTML",
                reply_markup=notes_markup(ps),
            )
            return

        if data == "gm_help":
            s = find_player_session(user_id)
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text="🕵️ <b>Game Help</b>\n\nUse the main Help command for the full command list.",
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user_id),
            )
            return

        if data == "gm_fate":
            s = find_player_session(user_id)
            if not s or not s.is_active():
                await query.answer("The oracle only speaks during an active game.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            answer = random.choice(ORACLE_YES + ORACLE_NO)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔮 <i>{html.escape(answer)}</i>",
                parse_mode="HTML",
            )
            return

        if data == "gm_message":
            s = find_player_session(user_id)
            if not s or not s.is_active() or user_id not in s.players:
                await query.answer("Messaging works only during active games.", show_alert=True)
                return
            await query.answer()
            await _show_player_pick(user_id, s, query.message, context)
            return

        if data == "gm_guide":
            s = find_player_session(user_id)
            await query.answer()
            await _send_guide_asset(
                context.bot,
                user_id,
                reply_markup=get_keyboard(s, user_id),
            )
            return

        # ── HOST TOOLS ───────────────────────────────────────────────────
        if data == "ht_startgame":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            ok, err = await _start_game_session(s, context)
            await query.answer("🎬 Game started!" if ok else err, show_alert=not ok)
            return

        if data.startswith("ht_menu:"):
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            menu = data.split(":", 1)[1]
            if menu not in {"main", "game", "roster", "info"}:
                await query.answer("Unknown menu.", show_alert=True)
                return
            await query.answer()
            await _show_host_tools_panel(query, s, menu)
            return

        if data == "ht_rename_menu":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_message(
                chat_id=user_id,
                text=_char_list_text(s, dev_mode=user_id in dev_mode_users),
                parse_mode="HTML",
                reply_markup=_character_list_dm_markup(s, user_id),
            )
            return

        if data == "ht_send_guide":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer("Guide sent to group.")
            await _send_guide_asset(context.bot, s.lobby_chat_id)
            await _show_host_tools_panel(query, s, "info", "📖 Guide sent to the group.")
            return

        if data == "ht_send_charlist":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer("Character list sent to group.")
            await context.bot.send_message(
                chat_id=s.lobby_chat_id,
                text=_char_list_text(s, dev_mode=user_id in dev_mode_users, show_name_hint=True),
                parse_mode="HTML",
            )
            await _show_host_tools_panel(query, s, "info", "📜 Character list sent to the group.")
            return

        if data == "ht_send_sus_group":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer("Suspicion table sent to group.")
            await context.bot.send_message(
                chat_id=s.lobby_chat_id,
                text=f"📊 <b>Suspicion Points</b>\n\n{sus_table_text(s)}",
                parse_mode="HTML",
            )
            await _show_host_tools_panel(query, s, "sus", "📊 Suspicion table sent to the group.")
            return

        if data == "ht_force_stop":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer("Force stopping game.")
            await end_game(s, context.bot, reason="force", purge=True)
            return

        if data == "ht_back":
            s = find_player_session(user_id)
            await query.answer()
            await query.edit_message_text(
                "🏠 <b>Private DM</b>\n\nUse the buttons below.",
                parse_mode="HTML",
                reply_markup=None,
            )
            if s:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🏠 <b>Private DM</b>\n\nUse the buttons below.",
                    parse_mode="HTML",
                    reply_markup=get_keyboard(s, user_id),
                )
            return

        if data == "game_end_confirm":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer()
            await query.edit_message_text(
                "🛑 <b>End the game?</b>\n\nThis will reveal secrets and stop the session.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Yes, end the game", callback_data="game_end_confirm_yes"),
                        InlineKeyboardButton("Cancel", callback_data="game_end_confirm_cancel"),
                    ],
                ]),
            )
            return

        if data == "game_end_confirm_cancel":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer()
            await _show_host_tools_panel(query, s, "game")
            return

        if data == "game_end_confirm_yes":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer()
            await end_game(s, context.bot, reason="host")
            return

        if data == "time_end_confirm:yes":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            await query.answer("Ending game now.")
            await end_game(s, context.bot, reason="time")
            return

        if data == "time_end_confirm:no":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("Host only.", show_alert=True)
                return
            s.triggers_paused = True
            s.final_timer_prompt_sent = True
            save_lobby_state()
            await query.answer("Timer paused.")
            try:
                await query.edit_message_text(
                    "⏸ <b>Timer paused.</b>\n\nNo more trigger cards will be sent.\nUse /endgame when you're ready.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

        # ── SUSPICION: show in group ──────────────────────────────────────
        if data == "sus_show_group":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_message(
                chat_id=s.lobby_chat_id,
                text=f"📊 <b>Suspicion Points</b>\n\n{sus_table_text(s)}",
                parse_mode="HTML",
            )
            return

        if data == "group_guide":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            await _send_guide_asset(context.bot, s.lobby_chat_id)
            return

        if data == "group_help":
            s = find_session_by_chat(query.message.chat_id)
            if not s:
                s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_message(
                chat_id=s.lobby_chat_id,
                text=_help_text(),
                parse_mode="HTML",
            )
            return

        # ── SUSPICION: show in DM ─────────────────────────────────────────
        if data == "sus_show_table":
            s = find_player_session(user_id)
            if not s:
                await query.answer("No game found.", show_alert=True)
                return
            await query.answer()
            await _show_host_tools_panel(query, s, "sus")
            return

        # ── SUSPICION: award list ─────────────────────────────────────────
        if data == "sus_award_list":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id or not s.is_active():
                await query.answer("No active game.", show_alert=True)
                return
            dev = user_id in dev_mode_users
            chars = s.all_character_names(dev_mode=dev)
            if not chars:
                await query.answer("No characters yet.", show_alert=True)
                return
            await query.answer()
            await query.edit_message_text(
                "➕ <b>Award sus point to…</b>",
                parse_mode="HTML",
                reply_markup=sus_char_list_markup(chars, s.npc_names),
            )
            return

        # ── SUSPICION: pick character ─────────────────────────────────────
        if data.startswith("sus_char:"):
            char_name = data.split(":", 1)[1]
            pending_sus_char[user_id] = char_name
            await query.answer()
            await query.edit_message_text(
                f"<b>{html.escape(char_name)}</b> — pick type:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🎬 In-Game", callback_data=f"sus_kind:in_game:{char_name[:50]}"),
                        InlineKeyboardButton("💬 In-Text", callback_data=f"sus_kind:in_text:{char_name[:50]}"),
                    ],
                    [InlineKeyboardButton("↩ Back", callback_data="sus_back")],
                ]),
            )
            return

        # ── SUSPICION: award kind ─────────────────────────────────────────
        if data.startswith("sus_kind:"):
            parts = data.split(":")
            kind = parts[1]
            char_name = ":".join(parts[2:])
            # Use find_player_session — more robust than find_host_session
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("No active game.", show_alert=True)
                return
            s.award_sus(char_name, kind)
            pts = s.sus_points.get(char_name, {"in_game": 0, "in_text": 0})
            kind_label = "In-Game" if kind == "in_game" else "In-Text"
            pending_sus_char.pop(user_id, None)
            save_lobby_state()
            await query.answer(f"✅ +1 {kind_label} → {char_name}")
            await _show_host_tools_panel(
                query,
                s,
                "sus",
                (
                    f"✅ <b>+1 {kind_label}</b> → <b>{html.escape(char_name)}</b>\n\n"
                    f"Total: In-Game {pts['in_game']} · In-Text {pts['in_text']}"
                ),
            )
            return

        # ── SUSPICION: back ───────────────────────────────────────────────
        if data == "sus_back":
            s = find_player_session(user_id)
            if not s or user_id != s.host_id:
                await query.answer("No game.", show_alert=True)
                return
            dev = user_id in dev_mode_users
            chars = s.all_character_names(dev_mode=dev)
            await query.answer()
            await query.edit_message_text(
                "➕ <b>Award sus point to…</b>",
                parse_mode="HTML",
                reply_markup=sus_char_list_markup(chars, s.npc_names),
            )
            return

        if data == "sus_cancel":
            pending_sus_char.pop(user_id, None)
            await query.answer()
            s = find_player_session(user_id)
            if s:
                await _show_host_tools_panel(query, s, "main", "Cancelled.")
            else:
                await query.edit_message_text("Cancelled.")
            return

        # ── NOTES: add ────────────────────────────────────────────────────
        if data == "note_add":
            s = find_player_session(user_id)
            if not s or user_id not in s.players:
                await query.answer("Not in game.", show_alert=True)
                return
            pending_note[user_id] = "add"
            await query.answer()
            await query.edit_message_text("✏️ Type your note now:")
            return

        # ── NOTES: pick action ────────────────────────────────────────────
        if data.startswith("note_pick:"):
            action = data.split(":", 1)[1]
            s = find_player_session(user_id)
            if not s or user_id not in s.players:
                await query.answer("Not in game.", show_alert=True)
                return
            ps = s.players[user_id]
            if not ps.notes:
                await query.answer("No notes yet.", show_alert=True)
                return
            await query.answer()
            await query.edit_message_text(
                f"Pick a note to {action}:",
                reply_markup=notes_pick_markup(ps, action),
            )
            return

        # ── NOTES: select ─────────────────────────────────────────────────
        if data.startswith("note_sel_:"):
            parts = data.split(":")
            action, idx = parts[1], int(parts[2])
            s = find_player_session(user_id)
            if not s or user_id not in s.players:
                await query.answer("Not in game.", show_alert=True)
                return
            ps = s.players[user_id]
            if idx >= len(ps.notes):
                await query.answer("Note not found.", show_alert=True)
                return

            if action == "del":
                ps.notes.pop(idx)
                save_lobby_state()
                await query.answer(f"🗑 Note {idx + 1} deleted")
                await query.edit_message_text(
                    notes_text(ps), parse_mode="HTML", reply_markup=notes_markup(ps)
                )
            elif action == "view":
                await query.answer()
                await query.edit_message_text(
                    f"📝 <b>Note {idx + 1}</b>\n\n{html.escape(ps.notes[idx])}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ Back", callback_data="note_back")]]),
                )
            elif action == "edit":
                pending_note[user_id] = f"edit:{idx}"
                await query.answer()
                current_note = ps.notes[idx].replace("\n", " ").strip()
                preview = html.escape(current_note[:160])
                if len(current_note) > 160:
                    preview += "..."
                await query.edit_message_text(
                    f"✏️ <b>Editing note {idx + 1}</b>\n\n"
                    f"📝 <b>Current note:</b> {preview}\n\n"
                    f"Send the updated text as a new message, or type <code>cancel</code>:",
                    parse_mode="HTML",
                )
            return

        # ── NOTES: back ───────────────────────────────────────────────────
        if data == "note_back":
            s = find_player_session(user_id)
            if not s or user_id not in s.players:
                await query.answer("Not in game.", show_alert=True)
                return
            ps = s.players[user_id]
            await query.answer()
            await query.edit_message_text(
                notes_text(ps), parse_mode="HTML", reply_markup=notes_markup(ps)
            )
            return

        if data == "note_close":
            await query.answer()
            await query.edit_message_text("📝 Notes closed. Use 📝 Notes to reopen.")
            return

        # ── MESSAGING: pick player ────────────────────────────────────────
        if data.startswith("dm_pick:") or data.startswith("msg_target:"):
            target_uid = int(data.split(":", 1)[1])
            s = find_player_session(user_id)
            if not s or target_uid not in s.players:
                await query.answer("Player not found.", show_alert=True)
                return
            await query.answer()
            await _show_message_route_pick(user_id, target_uid, s, query)
            return

        if data.startswith("dm_route:"):
            route = data.split(":", 1)[1]
            s = find_player_session(user_id)
            if not s or user_id not in s.players:
                await query.answer("You're not in a game.", show_alert=True)
                return
            target_uid = pending_dm_target.get(user_id)
            if target_uid is None or target_uid not in s.players:
                await query.answer("Choose a player first.", show_alert=True)
                return

            if route == "telegram":
                target = s.players[target_uid]
                url = _telegram_dm_url(target.username)
                if not url:
                    pending_dm_target.pop(user_id, None)
                    pending_dm_anon.pop(user_id, None)
                    pending_dm_route.pop(user_id, None)
                    await query.answer("That player does not have a public Telegram username.", show_alert=True)
                    return
                pending_dm_route[user_id] = "telegram"
                await query.answer()
                await query.edit_message_text(
                    "💬 Open Telegram and send the message there.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Through Telegram", url=url)],
                        [InlineKeyboardButton("↩ Back", callback_data="dm_cancel")],
                    ]),
                )
                pending_dm_target.pop(user_id, None)
                pending_dm_anon.pop(user_id, None)
                pending_dm_route.pop(user_id, None)
                return

            if route == "bot":
                pending_dm_route[user_id] = "bot"
                await query.answer()
                await query.edit_message_text(
                    "💬 Send your message as…",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("👤 Named", callback_data="dm_anon:no"),
                            InlineKeyboardButton("👻 Anonymous", callback_data="dm_anon:yes"),
                        ],
                        [InlineKeyboardButton("↩ Cancel", callback_data="dm_cancel")],
                    ]),
                )
                return

            await query.answer("Unknown route.", show_alert=True)
            return

        # ── MESSAGING: anon choice ────────────────────────────────────────
        if data.startswith("dm_anon:"):
            s = find_player_session(user_id)
            if not s or user_id not in s.players:
                await query.answer("You're not in a game.", show_alert=True)
                return
            if pending_dm_route.get(user_id) != "bot":
                await query.answer("Choose bot or Telegram first.", show_alert=True)
                return
            anon = data.split(":", 1)[1] == "yes"
            pending_dm_anon[user_id] = anon
            await query.answer()
            await query.edit_message_text(
                f"💬 Type your {'anonymous ' if anon else ''}message:"
            )
            return

        if data == "dm_cancel":
            pending_dm_target.pop(user_id, None)
            pending_dm_route.pop(user_id, None)
            pending_dm_anon.pop(user_id, None)
            await query.answer()
            await query.edit_message_text("Cancelled.")
            return

        # ── ORACLE via inline button ──────────────────────────────────────
        if data == "fate":
            s = find_player_session(user_id)
            if not s or not s.is_active():
                await query.answer("The oracle only speaks during an active game.", show_alert=True)
                return
            await query.answer()
            await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            answer = random.choice(ORACLE_YES + ORACLE_NO)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔮 <i>{html.escape(answer)}</i>",
                parse_mode="HTML",
            )
            return

        # Fallback
        await query.answer()

    except Exception as e:
        logger.exception("Callback error for %r: %s", data, e)
        try:
            await query.answer(f"Something went wrong: {e}", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════════════


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    text = (update.message.text or "").strip()
    tl = text.lower()

    if bot_halted:
        if chat.type == "private":
            await update.message.reply_text(
                "⛔ The bot is currently stopped.\n"
                "Send /start in DM to restart it.",
                reply_markup=get_keyboard(None, user.id),
            )
        return

    # Groups use inline buttons only — plain text is ignored
    if chat.type in ("group", "supergroup"):
        return

    # ── PRIVATE DM ───────────────────────────────────────────────────────
    s = _session_for_user(user.id)
    if tl in PRIVATE_BUTTON_TEXTS or tl in TOP_LEVEL_BUTTON_TEXTS:
        _clear_input_state(user.id)

    # ── ReplyKeyboard button routing ──────────────────────────────────────
    if tl == "▶️ start game":
        await cmd_startgame(update, context)
        return

    if tl == "🛑 end game":
        await cmd_endgame(update, context)
        return

    if tl == "📜 show characters":
        await cmd_characterlist(update, context)
        return

    if tl == "🎯 sus points":
        await cmd_sus(update, context)
        return

    if tl == "➕ add npc":
        if not s or user.id != s.host_id or not s.is_active():
            await update.message.reply_text(
                "➕ NPC setup is host-only during active games.",
                reply_markup=get_keyboard(s, user.id),
            )
            return
        pending_npc[user.id] = s.game_id
        npc_list = "\n".join(f"• {n}" for n in s.npc_names) if s.npc_names else "(none yet)"
        await update.message.reply_text(
            f"🎭 <b>Add NPC</b>\n\n{npc_list}\n\nSend an NPC name, or type cancel.",
            parse_mode="HTML",
            reply_markup=get_keyboard(s, user.id),
        )
        return

    if tl in TOP_LEVEL_BUTTON_TEXTS:
        if tl == "🎮 game menu":
            if not s:
                await update.message.reply_text("No game found.", reply_markup=get_keyboard(s, user.id))
                return
            if user.id not in s.players:
                await update.message.reply_text("You're not in this game.", reply_markup=get_keyboard(s, user.id))
                return
            await _show_game_menu_message(update, context, s)
            return

    if tl == "🔗 join game":
        await update.message.reply_text(
            "Send: <code>/join GAMEID</code>",
            parse_mode="HTML",
            reply_markup=get_keyboard(s, user.id),
        )
        return

    if tl == "❓ help":
        await cmd_help(update, context)
        return

    if tl == "📖 guide":
        await cmd_guide(update, context)
        return

    if tl == "🔮 divine fate":
        await cmd_fate(update, context)
        return

    if tl == "📝 notes":
        await cmd_notes(update, context)
        return

    if tl == "💬 message player":
        await cmd_message(update, context)
        return

    # ── Pending: note input ───────────────────────────────────────────────
    if user.id in pending_note:
        mode = pending_note.pop(user.id)
        if tl == "cancel":
            ps = s.players[user.id] if s and user.id in s.players else None
            if ps:
                await update.message.reply_text(
                    notes_text(ps), parse_mode="HTML", reply_markup=notes_markup(ps)
                )
            else:
                await update.message.reply_text("Cancelled.", reply_markup=get_keyboard(s, user.id))
            return

        if not s or user.id not in s.players:
            await update.message.reply_text("⚠️ Game not found.")
            return

        ps = s.players[user.id]
        note_content = text[:300]
        if mode == "add":
            ps.notes.append(note_content)
            msg = f"✅ Note saved ({len(ps.notes)} total)"
        else:
            idx = int(mode.split(":", 1)[1])
            if idx < len(ps.notes):
                ps.notes[idx] = note_content
                msg = f"✅ Note {idx + 1} updated"
            else:
                ps.notes.append(note_content)
                msg = "✅ Note saved"

        save_lobby_state()

        await update.message.reply_text(msg, reply_markup=get_keyboard(s, user.id))
        await update.message.reply_text(notes_text(ps), parse_mode="HTML", reply_markup=notes_markup(ps))
        return

    # ── Pending: host rename ──────────────────────────────────────────────
    if user.id in pending_host_rename:
        game_id, kind, key = pending_host_rename.pop(user.id)
        if tl == "cancel":
            s_r = find_session(game_id)
            await update.message.reply_text("Cancelled.", reply_markup=get_keyboard(s_r, user.id))
            return
        s_r = find_session(game_id)
        if not s_r or user.id != s_r.host_id:
            await update.message.reply_text("⚠️ Session no longer available.")
            return
        new_name = text[:40]
        if kind == "player":
            target_uid = int(key)
            if target_uid not in s_r.players:
                await update.message.reply_text("⚠️ Player no longer in game.")
                return
            old = s_r.players[target_uid].character_name
            s_r.players[target_uid].character_name = new_name
            _move_sus_points(s_r, old, new_name)
            done = (
                f"✅ Renamed <b>{html.escape(s_r.players[target_uid].telegram_name)}</b> "
                f"→ <b>{html.escape(new_name)}</b>"
            )
            if s_r.is_active() and old != new_name and old != "Awaiting name":
                try:
                    await context.bot.send_message(
                        chat_id=s_r.lobby_chat_id,
                        text=f"✏️ <b>{html.escape(old)}</b> is now known as <b>{html.escape(new_name)}</b>.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        else:
            idx = int(key)
            if idx < 0 or idx >= len(s_r.npc_names):
                await update.message.reply_text("⚠️ NPC no longer available.")
                return
            old_npc = s_r.npc_names[idx]
            s_r.npc_names[idx] = new_name
            _move_sus_points(s_r, old_npc, new_name)
            done = f"✅ NPC renamed: <b>{html.escape(old_npc)}</b> → <b>{html.escape(new_name)}</b>"

        await update.message.reply_text(done, parse_mode="HTML", reply_markup=get_keyboard(s_r, user.id))
        await refresh_group_lobby(context.bot, s_r)
        save_lobby_state()
        return

    # ── Pending: NPC name ─────────────────────────────────────────────────
    if user.id in pending_npc:
        game_id = pending_npc.pop(user.id)
        if tl == "cancel":
            s_tmp = find_session(game_id)
            await update.message.reply_text("Cancelled.", reply_markup=get_keyboard(s_tmp, user.id))
            return
        s_npc = find_session(game_id)
        if not s_npc:
            await update.message.reply_text("⚠️ Game not found.")
            return
        npc_name = text[:40]
        if npc_name not in s_npc.npc_names:
            s_npc.npc_names.append(npc_name)
        npc_list = "\n".join(f"• {n}" for n in s_npc.npc_names)
        await update.message.reply_text(
            f"✅ NPC added: <b>{html.escape(npc_name)}</b>\n\n"
            f"<b>NPCs:</b>\n{html.escape(npc_list)}\n\nSend another name, or type cancel.",
            parse_mode="HTML",
            reply_markup=get_keyboard(s_npc, user.id),
        )
        pending_npc[user.id] = game_id
        await refresh_group_lobby(context.bot, s_npc)
        save_lobby_state()
        return

    # ── Pending: DM message text ──────────────────────────────────────────
    if user.id in pending_dm_target:
        if tl == "cancel":
            pending_dm_target.pop(user.id, None)
            pending_dm_route.pop(user.id, None)
            pending_dm_anon.pop(user.id, None)
            await update.message.reply_text("Cancelled.", reply_markup=get_keyboard(s, user.id))
            return

        target_uid = pending_dm_target.pop(user.id)
        is_anon = pending_dm_anon.pop(user.id, False)
        pending_dm_route.pop(user.id, None)

        if not s or target_uid not in s.players:
            await update.message.reply_text("⚠️ Game ended or player not found.")
            return

        sender_char = html.escape(s.players[user.id].character_name)
        target_char = html.escape(s.players[target_uid].character_name)
        body = html.escape(text)

        if is_anon:
            msg_text = f"💬 <b>Anonymous message</b>\n\n<b>To:</b> {target_char}\n\n{body}"
        else:
            msg_text = f"💌 <b>Message</b>\n\n<b>To:</b> {target_char}\n<b>From:</b> {sender_char}\n\n{body}"

        if target_uid < 0:
            if not (user.id in dev_mode_users and user.id == s.host_id):
                await update.message.reply_text("⚠️ Dummy messages are dev-only.", reply_markup=get_keyboard(s, user.id))
                return
            await context.bot.send_chat_action(chat_id=user.id, action=ChatAction.TYPING)
            await asyncio.sleep(random.uniform(0.5, 1.2))
            await context.bot.send_message(
                chat_id=user.id,
                text=msg_text,
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user.id),
            )
            await update.message.reply_text(
                "✅ Dev dummy preview shown. That message is what the dummy would receive.",
                reply_markup=get_keyboard(s, user.id),
            )
            return

        try:
            await context.bot.send_chat_action(chat_id=target_uid, action=ChatAction.TYPING)
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await context.bot.send_message(chat_id=target_uid, text=msg_text, parse_mode="HTML")
            await update.message.reply_text(
                f"✅ Message delivered to <b>{target_char}</b>.",
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user.id),
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Could not deliver: {e}",
                reply_markup=get_keyboard(s, user.id),
            )
        return

    # ── Pending: character name input ─────────────────────────────────────
    if user.id in pending_name_for_user:
        if tl == "cancel":
            pending_name_for_user.pop(user.id, None)
            await update.message.reply_text("Cancelled.", reply_markup=get_keyboard(s, user.id))
            return

        if tl in PRIVATE_BUTTON_TEXTS:
            await update.message.reply_text(
                "🎭 Send your character name as plain text (not a button).",
                reply_markup=get_keyboard(s, user.id),
            )
            return

        game_id = pending_name_for_user.pop(user.id)
        s_g = find_session(game_id)
        if not s_g or user.id not in s_g.players:
            await update.message.reply_text("⚠️ Game not found.")
            return

        await _apply_name(user, s_g, text[:40], context, update.message, priv=True)
        return

    # ── Safety net: player in lobby still needs a name ────────────────────
    if (
        s
        and not s.started
        and not s.ended
        and user.id in s.players
        and s.players[user.id].character_name == "Awaiting name"
        and tl not in PRIVATE_BUTTON_TEXTS
    ):
        await _apply_name(user, s, text[:40], context, update.message, priv=True)
        return

    # Fallback
    await update.message.reply_text(
        "🤖 Use the buttons or /help for available commands.",
        reply_markup=get_keyboard(s, user.id),
    )


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════


async def _apply_name(user, s: GameSession, new_name: str, context, reply_msg, priv: bool) -> None:
    old_name = s.players[user.id].character_name
    s.players[user.id].character_name = new_name
    _move_sus_points(s, old_name, new_name)
    kb = get_keyboard(s, user.id) if priv else None

    await reply_msg.reply_text(
        f"✅ Character name set: <b>{html.escape(new_name)}</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await refresh_group_lobby(context.bot, s)
    save_lobby_state()

    if s.is_active() and old_name != new_name and old_name != "Awaiting name":
        try:
            await context.bot.send_message(
                chat_id=s.lobby_chat_id,
                text=f"✏️ <b>{html.escape(old_name)}</b> is now known as <b>{html.escape(new_name)}</b>.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    if user.id != s.host_id and not s.started:
        try:
            await context.bot.send_message(
                chat_id=s.host_id,
                text=(
                    f"✅ <b>{html.escape(user.first_name or str(user.id))}</b> is ready as "
                    f"<i>{html.escape(new_name)}</i>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


async def _do_join(user, game_id: str, context, reply_msg, is_private: bool) -> None:
    s = find_session(game_id)
    kb = get_keyboard(None, user.id) if is_private else None

    if not s:
        await reply_msg.reply_text(
            f"❌ No game found with ID <code>{game_id}</code>. Check the code and try again.",
            parse_mode="HTML", reply_markup=kb,
        )
        return
    if s.ended:
        await reply_msg.reply_text("🏁 That game has already ended.", reply_markup=kb)
        return
    if s.started:
        await reply_msg.reply_text("🎬 That game already started — joining is closed.", reply_markup=kb)
        return
    if user.id in s.players:
        if user.id in pending_name_for_user:
            await reply_msg.reply_text(
                f"✅ You're already in game <code>{game_id}</code>.\nSend your character name here.",
                parse_mode="HTML",
                reply_markup=get_keyboard(s, user.id) if is_private else kb,
            )
        else:
            await reply_msg.reply_text(
                f"✅ You're already in game <code>{game_id}</code>.",
                parse_mode="HTML", reply_markup=kb,
            )
        return

    s.players[user.id] = PlayerState(
        telegram_name=user.first_name or "Player",
        telegram_id=user.id,
        username=user.username or "",
    )
    pending_name_for_user[user.id] = game_id

    await reply_msg.reply_text(
        f"🎮 Joined <code>{game_id}</code>!\nSend your character name in DM.",
        parse_mode="HTML", reply_markup=kb,
    )
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎮 You're in game <code>{game_id}</code>!\n\n"
                f"Send your <b>character name</b> now."
            ),
            parse_mode="HTML",
            reply_markup=get_keyboard(s, user.id),
        )
    except Exception:
        s.players.pop(user.id, None)
        pending_name_for_user.pop(user.id, None)
        await reply_msg.reply_text(
            "⚠️ I can't DM you. Open a chat with this bot, press Start, then try /join again."
        )
        return

    await refresh_group_lobby(context.bot, s)
    save_lobby_state()
    logger.info("%s joined game %s", user.first_name, game_id)


async def _show_player_pick(user_id: int, s: GameSession, reply_msg, context) -> None:
    dev_host = user_id in dev_mode_users and user_id == s.host_id
    others = {
        uid: ps
        for uid, ps in s.players.items()
        if uid != user_id and (uid >= 0 or dev_host)
    }
    if not others:
        await reply_msg.reply_text(
            "📭 No other players to message yet.",
            reply_markup=get_keyboard(s, user_id),
        )
        return
    rows = [
        [InlineKeyboardButton(
            f"{'🤖' if uid < 0 else '💬'} {html.escape(ps.character_name)}",
            callback_data=f"dm_pick:{uid}",
        )]
        for uid, ps in others.items()
    ]
    rows.append([InlineKeyboardButton("↩ Cancel", callback_data="dm_cancel")])
    await reply_msg.reply_text(
        "💬 <b>Choose a player to message:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _show_message_route_pick(user_id: int, target_uid: int, s: GameSession, query) -> None:
    target = s.players[target_uid]
    target_label = target.character_name if target.character_name != "Awaiting name" else target.telegram_name
    telegram_url = _telegram_dm_url(target.username)
    pending_dm_target[user_id] = target_uid
    route_rows = [[InlineKeyboardButton("Through bot", callback_data="dm_route:bot")]]
    if telegram_url:
        route_rows[0].append(InlineKeyboardButton("Through Telegram", url=telegram_url))
    else:
        route_rows[0].append(InlineKeyboardButton("Through Telegram", callback_data="dm_route:telegram"))
    route_rows.append([InlineKeyboardButton("↩ Cancel", callback_data="dm_cancel")])
    await query.edit_message_text(
        f"💬 Message <b>{html.escape(target_label)}</b> through…",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(route_rows),
    )


def _telegram_dm_url(username: str) -> str | None:
    username = (username or "").lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def _character_list_dm_markup(s: GameSession, uid: int) -> InlineKeyboardMarkup | None:
    rows = []
    if uid in s.players:
        ps = s.players[uid]
        label = ps.character_name if ps.character_name != "Awaiting name" else ps.telegram_name
        rows.append([InlineKeyboardButton(f"✏️ {label[:44]} (you)", callback_data="self_rename")])
    if uid == s.host_id:
        for pid, ps in s.players.items():
            if pid < 0 or pid == uid:
                continue
            label = ps.character_name if ps.character_name != "Awaiting name" else ps.telegram_name
            rows.append([InlineKeyboardButton(f"✏️ {label[:44]}", callback_data=f"host_rename_pick:{pid}")])
        for idx, npc_name in enumerate(s.npc_names):
            rows.append([InlineKeyboardButton(f"🎭 ✏️ {npc_name[:40]}", callback_data=f"host_rename_npc:{idx}")])
        rows.append([InlineKeyboardButton("➕ Add NPC", callback_data="add_npc_dm")])
    return InlineKeyboardMarkup(rows) if rows else None


async def _send_start_dm(context, s: GameSession, pid: int) -> None:
    ps = s.players[pid]
    try:
        await context.bot.send_chat_action(chat_id=pid, action=ChatAction.TYPING)
        await context.bot.send_message(
            chat_id=pid,
            text=(
                f"🎬 <b>The game begins.</b>\n\n"
                f"You are <b>{html.escape(ps.character_name)}</b>.\n\n"
                f"🤫 <b>Your Secret:</b>\n<i>{html.escape(ps.secret)}</i>\n\n"
                f"Trigger cards will arrive throughout the game.\n"
                f"Stay in character. Act on what you receive."
            ),
            parse_mode="HTML",
            reply_markup=get_keyboard(s, pid),
        )
    except Exception as e:
        logger.warning("Could not send start message to %s: %s", ps.telegram_name, e)


async def _start_game_session(s: GameSession, context) -> tuple[bool, str]:
    if s.started or s.ended:
        return False, "Game already started or ended."

    pending = s.pending_real_players()
    if pending:
        names = ", ".join(html.escape(s.players[p].telegram_name) for p in pending)
        return False, f"Waiting for character names from: {names}"

    real_count = sum(1 for uid in s.players if uid >= 0)
    min_players = 1 if s.host_id in dev_mode_users else 2
    if real_count < min_players:
        return False, f"Need at least {min_players} player(s) to start."

    if s.host_id in dev_mode_users:
        for did, (dname, dsecret) in DUMMY_PLAYERS.items():
            if did not in s.players:
                ps = PlayerState(telegram_name=dname, character_name=dname, telegram_id=did)
                ps.secret = dsecret
                s.players[did] = ps

    s.started = True
    s.start_time = _now()
    s.triggers_paused = False
    s.final_timer_prompt_sent = False
    save_lobby_state()

    pids = list(s.players.keys())
    shuffled_secrets = random.sample(PLAYER_SECRETS, k=min(len(pids), len(PLAYER_SECRETS)))
    for i, pid in enumerate(pids):
        if not s.players[pid].secret:
            s.players[pid].secret = shuffled_secrets[i % len(shuffled_secrets)]

    start_dm_tasks = [
        asyncio.create_task(_send_start_dm(context, s, pid))
        for pid in pids
        if pid >= 0
    ]
    if start_dm_tasks:
        await asyncio.gather(*start_dm_tasks, return_exceptions=True)

    s.trigger_task = asyncio.create_task(game_trigger_scheduler(s, context.bot))
    s.reminder_task = asyncio.create_task(group_reminder_loop(s, context.bot))

    await refresh_group_lobby(context.bot, s)
    try:
        await context.bot.send_message(
            chat_id=s.lobby_chat_id,
            text=(
                f"🎬 <b>Alice Is Missing is LIVE!</b>\n\n"
                f"Secrets have been sent to each player in DM.\n"
                f"Trigger cards will arrive throughout.\n"
                f"You have 95 minutes. Good luck."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    logger.info("Game %s started with %d players", s.game_id, len(pids))
    return True, ""
def _telegram_dm_url(username: str) -> str | None:
    username = (username or "").lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def _character_list_dm_markup(s: GameSession, uid: int) -> InlineKeyboardMarkup | None:
    rows = []
    if uid in s.players:
        ps = s.players[uid]
        label = ps.character_name if ps.character_name != "Awaiting name" else ps.telegram_name
        rows.append([InlineKeyboardButton(f"✏️ {label[:44]} (you)", callback_data="self_rename")])
    if uid == s.host_id:
        for pid, ps in s.players.items():
            if pid < 0 or pid == uid:
                continue
            label = ps.character_name if ps.character_name != "Awaiting name" else ps.telegram_name
            rows.append([InlineKeyboardButton(f"✏️ {label[:44]}", callback_data=f"host_rename_pick:{pid}")])
        for idx, npc_name in enumerate(s.npc_names):
            rows.append([InlineKeyboardButton(f"🎭 ✏️ {npc_name[:40]}", callback_data=f"host_rename_npc:{idx}")])
        rows.append([InlineKeyboardButton("➕ Add NPC", callback_data="add_npc_dm")])
    return InlineKeyboardMarkup(rows) if rows else None


async def _send_start_dm(context, s: GameSession, pid: int) -> None:
    ps = s.players[pid]
    try:
        await context.bot.send_chat_action(chat_id=pid, action=ChatAction.TYPING)
        await context.bot.send_message(
            chat_id=pid,
            text=(
                f"🎬 <b>The game begins.</b>\n\n"
                f"You are <b>{html.escape(ps.character_name)}</b>.\n\n"
                f"🤫 <b>Your Secret:</b>\n<i>{html.escape(ps.secret)}</i>\n\n"
                f"Trigger cards will arrive throughout the game.\n"
                f"Stay in character. Act on what you receive."
            ),
            parse_mode="HTML",
            reply_markup=get_keyboard(s, pid),
        )
    except Exception as e:
        logger.warning("Could not send start message to %s: %s", ps.telegram_name, e)


async def _start_game_session(s: GameSession, context) -> tuple[bool, str]:
    if s.started or s.ended:
        return False, "Game already started or ended."

    pending = s.pending_real_players()
    if pending:
        names = ", ".join(html.escape(s.players[p].telegram_name) for p in pending)
        return False, f"Waiting for character names from: {names}"

    real_count = sum(1 for uid in s.players if uid >= 0)
    min_players = 1 if s.host_id in dev_mode_users else 2
    if real_count < min_players:
        return False, f"Need at least {min_players} player(s) to start."

    if s.host_id in dev_mode_users:
        for did, (dname, dsecret) in DUMMY_PLAYERS.items():
            if did not in s.players:
                ps = PlayerState(telegram_name=dname, character_name=dname, telegram_id=did)
                ps.secret = dsecret
                s.players[did] = ps

    s.started = True
    s.start_time = _now()
    s.triggers_paused = False
    s.final_timer_prompt_sent = False
    save_lobby_state()

    pids = list(s.players.keys())
    shuffled_secrets = random.sample(PLAYER_SECRETS, k=min(len(pids), len(PLAYER_SECRETS)))
    for i, pid in enumerate(pids):
        if not s.players[pid].secret:
            s.players[pid].secret = shuffled_secrets[i % len(shuffled_secrets)]

    start_dm_tasks = [
        asyncio.create_task(_send_start_dm(context, s, pid))
        for pid in pids
        if pid >= 0
    ]
    if start_dm_tasks:
        await asyncio.gather(*start_dm_tasks, return_exceptions=True)

    s.trigger_task = asyncio.create_task(game_trigger_scheduler(s, context.bot))
    s.reminder_task = asyncio.create_task(group_reminder_loop(s, context.bot))

    await refresh_group_lobby(context.bot, s)
    try:
        await context.bot.send_message(
            chat_id=s.lobby_chat_id,
            text=(
                f"🎬 <b>Alice Is Missing is LIVE!</b>\n\n"
                f"Secrets have been sent to each player in DM.\n"
                f"Trigger cards will arrive throughout.\n"
                f"You have 95 minutes. Good luck."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    logger.info("Game %s started with %d players", s.game_id, len(pids))
    return True, ""


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)
