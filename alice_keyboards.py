"""alice_keyboards.py — All keyboard layouts."""

from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

# ─── texts that should never be treated as a character name ──────────────────
TOP_LEVEL_BUTTON_TEXTS = {
    "🎮 game menu",
}

PRIVATE_BUTTON_TEXTS = {
    *TOP_LEVEL_BUTTON_TEXTS,
    # legacy fallbacks (old keyboard still floating in some chats)
    "🔗 join game",
    "📋 status",
    "📜 show characters",
    "▶️ start game",
    "🛑 end game",
    "💬 message player",
    "🔮 divine fate",
    "📝 notes",
    "🎯 sus points",
    "➕ add npc",
    "❓ help",
    "📖 guide",
    "✏️ rename entries",
    "➕ add sus point",
    "📊 send sus point table to group",
    "📖 send guide to group",
    "📜 send character list to group",
    "⛔ force stop / kill game",
    "🔧 host tools",
}


# ─── Reply keyboard (persistent bottom bar) ───────────────────────────────────

def get_keyboard(session, uid: int) -> ReplyKeyboardMarkup:
    """Phase-aware DM keyboard. Groups never receive this."""
    # No session or ended
    if session is None or session.ended:
        return ReplyKeyboardMarkup(
            [["🔗 Join Game", "📖 Guide"], ["❓ Help"]],
            resize_keyboard=True,
        )

    is_host = uid == session.host_id

    if session.is_lobby():
        if is_host:
            return ReplyKeyboardMarkup(
                [
                    ["📜 Show Characters", "▶️ Start Game"],
                    ["🛑 End Game", "❓ Help"],
                    ["📖 Guide"],
                ],
                resize_keyboard=True,
            )
        return ReplyKeyboardMarkup(
            [
                ["📜 Show Characters"],
                ["❓ Help", "📖 Guide"],
            ],
            resize_keyboard=True,
        )

    if session.is_active():
        if is_host:
            return ReplyKeyboardMarkup(
                [
                    ["💬 Message Player", "🔮 Divine Fate"],
                    ["📝 Notes", "🎯 Sus Points"],
                    ["📜 Show Characters"],
                    ["❓ Help", "📖 Guide"],
                ],
                resize_keyboard=True,
            )
        return ReplyKeyboardMarkup(
            [
                ["💬 Message Player", "🔮 Divine Fate"],
                ["📝 Notes", "🎯 Sus Points"],
                ["📜 Show Characters"],
                ["❓ Help", "📖 Guide"],
            ],
            resize_keyboard=True,
        )

    # Fallback for any unusual state
    return ReplyKeyboardMarkup(
        [["🔗 Join Game", "❓ Help"], ["📖 Guide"]],
        resize_keyboard=True,
    )


# ─── Inline: top-level menu picker (shown when ↩ Back is pressed) ────────────

def main_menu_inline(session, uid: int) -> InlineKeyboardMarkup:
    """Legacy fallback. No chooser screen anymore."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩ Back", callback_data="menu_back")],
    ])


# ─── Inline: Game Menu ────────────────────────────────────────────────────────

def game_menu_inline(session, uid: int) -> InlineKeyboardMarkup:
    """Legacy fallback for old messages."""
    rows = [
        [
            InlineKeyboardButton("💬 Message Player", callback_data="gm_message"),
            InlineKeyboardButton("🔮 Oracle / Divine Fate", callback_data="gm_fate"),
        ],
        [InlineKeyboardButton("📜 Show Character List", callback_data="gm_charlist")],
        [InlineKeyboardButton("📊 Show Sus Points", callback_data="gm_sus_view")],
        [InlineKeyboardButton("📝 Notes", callback_data="gm_notes")],
        [InlineKeyboardButton("❓ Help", callback_data="gm_help")],
        [InlineKeyboardButton("↩ Back", callback_data="menu_back")],
    ]
    return InlineKeyboardMarkup(rows)


# ─── Inline: Host Tools ───────────────────────────────────────────────────────

def host_tools_inline(session, menu: str = "main") -> InlineKeyboardMarkup:
    """Host-only tools inline menu, split into smaller focused panels."""
    is_lobby = bool(session and session.is_lobby())
    is_active = bool(session and session.is_active())

    if menu == "main":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Game Control", callback_data="ht_menu:game")],
            [InlineKeyboardButton("🎯 Suspicion", callback_data="ht_menu:sus")],
            [InlineKeyboardButton("🧭 Roster", callback_data="ht_menu:roster")],
            [InlineKeyboardButton("📖 Info & Guide", callback_data="ht_menu:info")],
            [InlineKeyboardButton("↩ Back", callback_data="ht_back")],
        ])

    if menu == "game":
        rows = []
        if is_lobby:
            rows.append([InlineKeyboardButton("▶️ Start Game", callback_data="ht_startgame")])
        if is_lobby or is_active:
            rows.append([InlineKeyboardButton("🛑 End Game", callback_data="game_end_confirm")])
        rows.append([InlineKeyboardButton("⛔ Force Stop Bot", callback_data="ht_force_stop")])
        rows.append([InlineKeyboardButton("↩ Back", callback_data="ht_back")])
        return InlineKeyboardMarkup(rows)

    if menu == "sus":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Sus Point", callback_data="sus_award_list")],
            [
                InlineKeyboardButton("📊 DM Table", callback_data="sus_show_table"),
                InlineKeyboardButton("📊 Post Group", callback_data="sus_show_group"),
            ],
            [InlineKeyboardButton("↩ Back", callback_data="ht_back")],
        ])

    if menu == "roster":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Rename Entries", callback_data="ht_rename_menu")],
            [InlineKeyboardButton("➕ Add NPC", callback_data="add_npc_dm")],
            [InlineKeyboardButton("↩ Back", callback_data="ht_back")],
        ])

    if menu == "info":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Send Guide to Group", callback_data="ht_send_guide")],
            [InlineKeyboardButton("📜 Send Character List to Group", callback_data="ht_send_charlist")],
            [InlineKeyboardButton("↩ Back", callback_data="ht_back")],
        ])

    return host_tools_inline(session, "main")


# ─── Notes ────────────────────────────────────────────────────────────────────

def notes_markup(ps) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Add Note", callback_data="note_add")]]
    if ps.notes:
        rows.append([
            InlineKeyboardButton("👁 View", callback_data="note_pick:view"),
            InlineKeyboardButton("✏️ Edit", callback_data="note_pick:edit"),
            InlineKeyboardButton("🗑 Delete", callback_data="note_pick:del"),
        ])
    return InlineKeyboardMarkup(rows)


def notes_pick_markup(ps, action: str) -> InlineKeyboardMarkup:
    rows = []
    for i, note in enumerate(ps.notes):
        preview = note[:30] + ("..." if len(note) > 30 else "")
        rows.append([InlineKeyboardButton(
            f"{i + 1}. {preview}",
            callback_data=f"note_sel_:{action}:{i}",
        )])
    rows.append([InlineKeyboardButton("↩ Back", callback_data="note_back")])
    return InlineKeyboardMarkup(rows)


# ─── Suspicion ────────────────────────────────────────────────────────────────

def sus_award_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Sus Point", callback_data="sus_award_list")],
        [InlineKeyboardButton("📊 Send Table to Group", callback_data="sus_show_group")],
    ])


def sus_char_list_markup(chars: list, npc_names: list) -> InlineKeyboardMarkup:
    rows = []
    for name in chars:
        tag = "🎭" if name in npc_names else "👤"
        rows.append([InlineKeyboardButton(
            f"{tag} {name}", callback_data=f"sus_char:{name[:50]}"
        )])
    rows.append([InlineKeyboardButton("↩ Cancel", callback_data="sus_cancel")])
    return InlineKeyboardMarkup(rows)
