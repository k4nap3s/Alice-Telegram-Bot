"""
alice_helpers.py — Game logic, loops, session management, and state helpers.
"""

import asyncio
import random
import logging
import html
from datetime import datetime, timezone, timedelta

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction

from alice_models import GameSession, PlayerState, GAME_DURATION_MINUTES
from alice_keyboards import get_keyboard
from content import EARLY_TRIGGERS, MID_TRIGGERS, LATE_TRIGGERS, GROUP_REMINDERS

logger = logging.getLogger(__name__)
UTC = timezone.utc

# ─────────────────────────────────────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────────────────────────────────────

games: dict[str, GameSession] = {}

pending_name_for_user: dict[int, str] = {}
pending_dm_target: dict[int, int] = {}
pending_dm_route: dict[int, str] = {}
pending_dm_anon: dict[int, bool] = {}
pending_note: dict[int, str] = {}
pending_npc: dict[int, str] = {}
pending_sus_char: dict[int, str] = {}
pending_host_rename: dict[int, tuple[str, str, str]] = {}

dev_mode_users: set[int] = set()

_LOBBY_STATE_FILE = "lobby_state.json"


# ─────────────────────────────────────────────────────────────────────────────
# Session finders
# ─────────────────────────────────────────────────────────────────────────────

def find_session(game_id: str) -> GameSession | None:
    return games.get(game_id)


def find_host_session(uid: int) -> GameSession | None:
    for s in games.values():
        if s.host_id == uid and not s.ended:
            return s
    return None


def find_player_session(uid: int) -> GameSession | None:
    """Find an active session where uid is a player OR the host."""
    for s in games.values():
        if not s.ended and uid in s.players:
            return s
    # Fallback: user might be host but not yet in players dict (shouldn't happen, but be safe)
    for s in games.values():
        if not s.ended and s.host_id == uid:
            return s
    return None


def find_session_by_chat(chat_id: int) -> GameSession | None:
    for s in games.values():
        if s.lobby_chat_id == chat_id and not s.ended:
            return s
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Lobby state persistence
# ─────────────────────────────────────────────────────────────────────────────

def save_lobby_state() -> None:
    """Persist game state to disk (best-effort)."""
    import json
    try:
        data = {}
        for gid, s in games.items():
            if s.ended:
                continue
            players_data = {}
            for uid, ps in s.players.items():
                players_data[str(uid)] = {
                    "telegram_name": ps.telegram_name,
                    "telegram_id": ps.telegram_id,
                    "username": ps.username,
                    "character_name": ps.character_name,
                    "secret": ps.secret,
                    "notes": ps.notes,
                    "triggers_sent": ps.triggers_sent,
                }
            # Always save start_time with timezone offset so it round-trips cleanly
            st_str = None
            if s.start_time:
                st = s.start_time
                if st.tzinfo is None:
                    st = st.replace(tzinfo=UTC)
                st_str = st.isoformat()
            data[gid] = {
                "game_id": s.game_id,
                "host_id": s.host_id,
                "lobby_chat_id": s.lobby_chat_id,
                "host_telegram_name": s.host_telegram_name,
                "players": players_data,
                "npc_names": s.npc_names,
                "started": s.started,
                "ended": s.ended,
                "start_time": st_str,
                "lobby_msg_id": s.lobby_msg_id,
                "sus_points": s.sus_points,
                "triggers_paused": s.triggers_paused,
                "final_timer_prompt_sent": s.final_timer_prompt_sent,
            }
        with open(_LOBBY_STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save lobby state: %s", e)


def load_lobby_state() -> None:
    """Load persisted game state from disk (best-effort)."""
    import json
    try:
        with open(_LOBBY_STATE_FILE) as f:
            data = json.load(f)
        seen_lobby_chats: set[int] = set()
        seen_hosts: set[int] = set()
        for gid, raw in data.items():
            lobby_chat_id = int(raw["lobby_chat_id"])
            host_id = int(raw["host_id"])
            if lobby_chat_id in seen_lobby_chats or host_id in seen_hosts:
                logger.warning(
                    "Skipping duplicate loaded session %s for chat %s / host %s",
                    gid, lobby_chat_id, host_id,
                )
                continue
            players = {}
            for uid_str, pd in raw["players"].items():
                uid = int(uid_str)
                ps = PlayerState(
                    telegram_name=pd["telegram_name"],
                    telegram_id=pd["telegram_id"],
                    username=pd.get("username", ""),
                    character_name=pd.get("character_name", "Awaiting name"),
                    secret=pd.get("secret", ""),
                    notes=pd.get("notes", []),
                    triggers_sent=pd.get("triggers_sent", 0),
                )
                players[uid] = ps

            # Ensure start_time is always timezone-aware
            start_time = None
            if raw.get("start_time"):
                st = datetime.fromisoformat(raw["start_time"])
                if st.tzinfo is None:
                    st = st.replace(tzinfo=UTC)
                start_time = st

            s = GameSession(
                game_id=raw["game_id"],
                host_id=host_id,
                lobby_chat_id=lobby_chat_id,
                host_telegram_name=raw.get("host_telegram_name", ""),
                players=players,
                npc_names=raw.get("npc_names", []),
                started=raw.get("started", False),
                ended=raw.get("ended", False),
                start_time=start_time,
                lobby_msg_id=raw.get("lobby_msg_id"),
                sus_points=raw.get("sus_points", {}),
                triggers_paused=raw.get("triggers_paused", False),
                final_timer_prompt_sent=raw.get("final_timer_prompt_sent", False),
            )
            games[gid] = s
            seen_lobby_chats.add(lobby_chat_id)
            seen_hosts.add(host_id)
        logger.info("Loaded %d game(s) from state file.", len(games))
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("Failed to load lobby state: %s", e)


def clear_session_runtime_state(s: GameSession) -> None:
    """Clear all pending interaction state tied to a session."""
    user_ids = set(s.players.keys()) | {s.host_id}
    for uid in user_ids:
        pending_name_for_user.pop(uid, None)
        pending_dm_target.pop(uid, None)
        pending_dm_route.pop(uid, None)
        pending_dm_anon.pop(uid, None)
        pending_note.pop(uid, None)
        pending_npc.pop(uid, None)
        pending_sus_char.pop(uid, None)
        pending_host_rename.pop(uid, None)


# ─────────────────────────────────────────────────────────────────────────────
# Group lobby message
# ─────────────────────────────────────────────────────────────────────────────

def _lobby_keyboard(s: GameSession) -> InlineKeyboardMarkup:
    """Compact inline keyboard for the pinned group lobby card — NO close button."""
    rows = [[
        InlineKeyboardButton("📜 Characters", callback_data="char_list"),
    ]]
    if s.is_active():
        rows[0].append(InlineKeyboardButton("🎯 Sus Points", callback_data="sus_show_group"))
    rows.extend([
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
    return InlineKeyboardMarkup(rows)


def _lobby_text(s: GameSession) -> str:
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
    elif s.is_active():
        elapsed = int(s.elapsed_minutes())
        remaining = int(s.remaining_minutes())
        return (
            f"🎬 <b>Alice Is Missing — LIVE</b>\n"
            f"<b>Game ID:</b> <code>{s.game_id}</code>\n"
            f"<b>Phase:</b> {s.game_phase().capitalize()} · {elapsed} min elapsed · {remaining} min left\n\n"
            f"{s.roster_text()}\n\n"
            f"The story is unfolding. Stay in character."
        )
    else:
        return f"🏁 <b>Game {s.game_id} has ended.</b>"


async def update_group_lobby(bot: Bot, s: GameSession) -> None:
    """Create or edit the sticky lobby message in the group chat."""
    text = _lobby_text(s)
    markup = _lobby_keyboard(s)
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
        try:
            await bot.pin_chat_message(
                chat_id=s.lobby_chat_id,
                message_id=s.lobby_msg_id,
                disable_notification=True,
            )
        except Exception as e:
            logger.warning("Could not pin lobby message: %s", e)
    except Exception as e:
        logger.warning("Could not update group lobby: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# End game
# ─────────────────────────────────────────────────────────────────────────────

async def end_game(s: GameSession, bot: Bot, reason: str = "host", purge: bool = False) -> None:
    """Cleanly end a game session."""
    if s.ended:
        if purge:
            games.pop(s.game_id, None)
            save_lobby_state()
        return

    s.ended = True
    s.end_time = datetime.now(tz=UTC)
    clear_session_runtime_state(s)

    current_task = asyncio.current_task()

    # Cancel player trigger loops (can be sleeping for many minutes)
    for task in s.player_tasks.values():
        if task and not task.done():
            task.cancel()
    if s.trigger_task and s.trigger_task is not current_task and not s.trigger_task.done():
        s.trigger_task.cancel()
    if s.reminder_task and s.reminder_task is not current_task and not s.reminder_task.done():
        s.reminder_task.cancel()
    s.player_tasks.clear()
    s.trigger_inflight.clear()
    s.trigger_task = None
    s.reminder_task = None

    # Send final reveal to each real player
    real_players = [uid for uid in s.players if uid >= 0]
    real_count = len(real_players)
    elapsed = int(s.elapsed_minutes())
    for uid, ps in s.players.items():
        if uid < 0:
            continue
        try:
            await bot.send_message(
                chat_id=uid,
                text=(
                    f"🏁 <b>The game has ended.</b>\n\n"
                    f"You were <b>{html.escape(ps.character_name)}</b>.\n\n"
                    f"🤫 <b>Your Secret:</b>\n"
                    f"<i>{html.escape(ps.secret)}</i>\n\n"
                    f"Now reveal your secrets in the group and determine what happened to Alice."
                ),
                parse_mode="HTML",
                reply_markup=get_keyboard(None, uid),
            )
        except Exception as e:
            logger.warning("Could not send end message to %s: %s", ps.telegram_name, e)

    # Group announcement
    if reason == "time":
        reason_text = "The timer ended the session."
    elif reason == "force":
        reason_text = "The session was force-stopped."
    else:
        reason_text = "The host ended the session."

    try:
        await bot.send_message(
            chat_id=s.lobby_chat_id,
            text=(
                f"🏁 <b>The game has ended.</b>\n\n"
                f"{reason_text}\n"
                f"Duration: {elapsed} min · {real_count} players\n\n"
                f"Whatever you know about Alice — it's time to share"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Could not send end message to group: %s", e)

    await update_group_lobby(bot, s)
    if purge:
        games.pop(s.game_id, None)
    save_lobby_state()
    logger.info("Game %s ended (reason: %s)", s.game_id, reason)


# ─────────────────────────────────────────────────────────────────────────────
# Trigger scheduler
# ─────────────────────────────────────────────────────────────────────────────

def _pick_trigger(phase: str, used: set) -> str | None:
    """Pick an unused trigger for the given phase."""
    pool = {
        "early": EARLY_TRIGGERS,
        "mid": MID_TRIGGERS,
        "late": LATE_TRIGGERS,
    }.get(phase, EARLY_TRIGGERS)

    available = [t for t in pool if t not in used]
    if not available:
        all_triggers = EARLY_TRIGGERS + MID_TRIGGERS + LATE_TRIGGERS
        available = [t for t in all_triggers if t not in used]
    if not available:
        return None
    return random.choice(available)


async def game_trigger_scheduler(s: GameSession, bot: Bot) -> None:
    """Deliver trigger cards for all players in one shared scheduler."""
    TOTAL_TRIGGERS = 15
    TOTAL_SECONDS = GAME_DURATION_MINUTES * 60
    interval = TOTAL_SECONDS / TOTAL_TRIGGERS
    used_triggers: dict[int, set[str]] = {}

    try:
        while not s.ended:
            if s.triggers_paused:
                return
            now = datetime.now(tz=UTC)
            if not s.start_time:
                await asyncio.sleep(1)
                continue

            active_player_ids = [
                uid for uid, ps in s.players.items()
                if uid >= 0 and ps.triggers_sent < TOTAL_TRIGGERS
            ]
            if not active_player_ids:
                return

            progress_made = False
            for uid in active_player_ids:
                if s.ended:
                    return
                if s.triggers_paused:
                    return
                if uid in s.trigger_inflight:
                    continue
                ps = s.players.get(uid)
                if not ps or ps.triggers_sent >= TOTAL_TRIGGERS:
                    continue

                trigger_index = ps.triggers_sent + 1
                due_at = s.start_time + timedelta(seconds=interval * trigger_index)
                if now < due_at:
                    continue

                phase = s.game_phase()
                pending = used_triggers.setdefault(uid, set())
                trigger = _pick_trigger(phase, pending)
                if not trigger:
                    continue

                s.trigger_inflight.add(uid)
                progress_made = True
                try:
                    await bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)
                    await asyncio.sleep(2)
                    if s.ended:
                        return
                    await bot.send_message(
                        chat_id=uid,
                        text=(
                            f"🃏 <b>Trigger Card #{ps.triggers_sent + 1}</b>\n\n"
                            f"<i>{html.escape(trigger)}</i>"
                        ),
                        parse_mode="HTML",
                    )
                    ps.triggers_sent += 1
                    pending.add(trigger)
                    logger.info(
                        "Sent trigger %d to %s (game %s)",
                        ps.triggers_sent,
                        ps.telegram_name,
                        s.game_id,
                    )
                except Exception as e:
                    logger.warning("Could not send trigger to %s: %s", ps.telegram_name, e)
                finally:
                    s.trigger_inflight.discard(uid)

            if not progress_made:
                await asyncio.sleep(2)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception("Trigger loop error for uid %d: %s", uid, e)


# ─────────────────────────────────────────────────────────────────────────────
# Group reminder loop
# ─────────────────────────────────────────────────────────────────────────────

async def group_reminder_loop(s: GameSession, bot: Bot) -> None:
    """Send group reminders at scheduled time marks.

    This loop announces scheduled reminders and then asks the host whether to
    end the session when the final timer mark is reached.
    """
    schedule = _group_reminder_schedule()
    sent_marks: set[object] = set()
    try:
        while not s.ended:
            elapsed = s.elapsed_minutes()

            for idx, (due_minute, text) in enumerate(schedule):
                if idx in sent_marks or elapsed < due_minute:
                    continue
                sent_marks.add(idx)
                try:
                    await bot.send_message(
                        chat_id=s.lobby_chat_id,
                        text=text,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning("Could not send reminder: %s", e)

            if len(sent_marks) >= len(schedule) and not s.final_timer_prompt_sent:
                s.final_timer_prompt_sent = True
                s.triggers_paused = True
                save_lobby_state()
                try:
                    await bot.send_message(
                        chat_id=s.host_id,
                        text=(
                            "⏰ <b>Final timer reached.</b>\n\n"
                            "Do you want to end the game now?\n"
                            "If you keep it open, no more trigger cards will be sent."
                        ),
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("Yes, end now", callback_data="time_end_confirm:yes"),
                                InlineKeyboardButton("Keep it open", callback_data="time_end_confirm:no"),
                            ],
                        ]),
                    )
                except Exception as e:
                    logger.warning("Could not send final timer prompt: %s", e)
                    try:
                        await bot.send_message(
                            chat_id=s.lobby_chat_id,
                            text=(
                                "⏰ <b>Final timer reached.</b>\n\n"
                                "Host confirmation is needed to end the game.\n"
                                "No more trigger cards will be sent."
                            ),
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup([
                                [
                                    InlineKeyboardButton("Yes, end now", callback_data="time_end_confirm:yes"),
                                    InlineKeyboardButton("Keep it open", callback_data="time_end_confirm:no"),
                                ],
                            ]),
                        )
                    except Exception:
                        pass
                return

            next_due = next(
                (due_minute for idx, (due_minute, _) in enumerate(schedule) if idx not in sent_marks),
                None,
            )
            if next_due is None:
                sleep_for = 10
            else:
                sleep_for = max(1.0, min(60.0, (next_due - elapsed) * 60.0))

            await asyncio.sleep(sleep_for)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception("Reminder loop error for game %s: %s", s.game_id, e)


def _group_reminder_schedule() -> list[tuple[float, str]]:
    """Convert countdown labels into elapsed-time send points.

    The first reminder is sent immediately at game start, then each later card
    waits for the difference between its label and the previous one.
    """
    schedule: list[tuple[float, str]] = []
    elapsed_minute = 0.0
    previous_mark: int | None = None
    for mark, text in GROUP_REMINDERS:
        if previous_mark is None:
            elapsed_minute = 0.0
        else:
            elapsed_minute += max(0, previous_mark - mark)
        schedule.append((elapsed_minute, text))
        previous_mark = mark
    return schedule


async def restore_active_sessions(app) -> None:
    """Recreate background tasks after a bot restart."""
    for s in list(games.values()):
        if s.ended or not s.started:
            continue
        if s.triggers_paused:
            continue
        if s.trigger_task is None or s.trigger_task.done():
            s.trigger_task = app.create_task(game_trigger_scheduler(s, app.bot))
        if s.reminder_task is None or s.reminder_task.done():
            s.reminder_task = app.create_task(group_reminder_loop(s, app.bot))


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────────────────────────────────────

def notes_text(ps: PlayerState) -> str:
    if not ps.notes:
        return "📝 <b>Your Journal</b>\n\n(No entries yet. Add one to keep track of clues.)"
    lines = ["📝 <b>Your Journal</b>\n"]
    for i, note in enumerate(ps.notes, 1):
        preview = note[:30] + ("..." if len(note) > 30 else "")
        lines.append(f"{i}. {html.escape(preview)}")
    return "\n".join(lines)


def sus_table_text(s: GameSession) -> str:
    lines = []
    roster: list[str] = []
    seen: set[str] = set()

    for ps in s.players.values():
        if ps.character_name and ps.character_name != "Awaiting name" and ps.character_name not in seen:
            roster.append(ps.character_name)
            seen.add(ps.character_name)
    for npc in s.npc_names:
        if npc not in seen:
            roster.append(npc)
            seen.add(npc)
    for name in s.sus_points:
        if name not in seen:
            roster.append(name)
            seen.add(name)

    if not roster:
        return "<i>(no characters yet)</i>"

    rows = []
    for name in roster:
        pts = s.sus_points.get(name, {"in_game": 0, "in_text": 0}) or {}
        ig = int(pts.get("in_game", 0) or 0)
        it = int(pts.get("in_text", 0) or 0)
        rows.append((name, ig + it, ig, it, "🎭" if name in s.npc_names else "👤"))

    rows.sort(key=lambda item: (-item[1], item[0].lower()))
    for rank, (name, total, ig, it, tag) in enumerate(rows, 1):
        safe_name = html.escape(name[:32])
        lines.append(f"{rank}. {tag} <b>{safe_name}</b>")
        lines.append(f"   ├ Total: {total}")
        lines.append(f"   ├ In-Game: {ig}  │  In-Text: {it}")
        lines.append("")
    return "\n".join(lines).rstrip()
