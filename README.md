# Alice Is Missing — Telegram RPG Bot

A silent mystery roleplaying game bot for Telegram. Players solve Alice's disappearance through 95 minutes of trigger cards and secret-keeping.

## Quick Start

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
python main.py
```

## Features

| Feature | Details |
|---------|---------|
| 🎮 **Trigger Cards** | 15 unique per player, spread across 95 minutes |
| ⏱️ **Typing Animation** | 90 seconds of "typing..." before each trigger |
| 📝 **Personal Notes** | Add, edit, delete notes privately |
| 🎯 **Suspicion Tracking** | In-game and in-text point awards |
| 💬 **Player Messaging** | Anonymous or named DMs |
| 🔮 **Divine Fate** | Ask yes/no questions |
| 🎭 **NPC Management** | Host adds NPCs during lobby |
| 🔑 **Secrets** | Each player gets a unique secret |
| 🎮 **Phase-Aware UI** | Buttons change based on game state |
| 🔘 **Dual Controls** | Buttons + slash commands (triple redundancy) |

## Commands

**Group Chat**
- `/newgame` — Create a lobby
- `/status` — Show the game state
- `/characterlist` — Show the roster
- `/showsus` — Show suspicion points

**Private DM**
- `/start` — Open or restart the bot DM
- `/join GAMEID` — Join a game
- `/name NAME` — Set or change your character name
- `/message` — Send a DM to another player
- `/notes` — View or edit notes
- `/fate` — Ask the oracle
- `/cancel` — Cancel the current pending action
- `/guide` — How to play

**Host Only**
- `/startgame` — Start the game
- `/endgame` — End the game
- `/forcestop` — Stop the bot and active sessions
- `/sus` — Award suspicion points
- `/addnpc` — Add an NPC
- `/sendguide` — Send the guide to the group
- `/sendcharlist` — Send the character list to the group
- `/postsus` — Send the suspicion table to the group

**Dev / Testing**
- `/dev alice` — Toggle solo test mode

## How to Play

**Setup (Lobby Phase):**
1. Host runs `/newgame` in group chat
2. Players tap "🔗 Join Game" button
3. Set character name in DMs
4. Host taps "▶️ Start Game"

**Gameplay (Active Phase):**
- Receive a secret only you know
- Get trigger cards — act on them in group or DMs
- Message other players (anonymous or named)
- Ask the oracle about uncertain events
- Track clues in personal notes

**Ending:**
- Host ends game with `/endgame` or 🛑 **End Game** button
- Reveal your secrets
- Determine what happened to Alice

## Controls

### Buttons (Primary)

**Group Chat:**
*Buttons change based on game phase:*
- 🔗 Join Game (Lobby only)
- ▶️ Start Game (Lobby only)
- 📜 Show Characters (Active only)
- 🎯 Sus Points (Active only)
- 🛑 End Game (Lobby & Active)
- ✕ Close (All phases)

**Private Messages:**
Changes based on game phase. Available during gameplay:
- 🔮 Divine Fate
- 💬 Message Player
- 📝 Notes
- 🎯 Sus Points (host only)
- ➕ Add NPC (host only)
- 📋 Status
- ❓ Help

### Slash Commands (Fallback)

Every button also works as a slash command for reliability.

## Game Phases

| Phase | Duration | What Happens |
|-------|----------|--------------|
| **Lobby** | Before start | Players join, set names, host adds NPCs |
| **Active** | Until host ends | Triggers arrive, players communicate, mysteries unfold |
| **Ended** | After /endgame | Game stops, secrets revealed, winner determined |

## Architecture

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | 86 | Entry point, handler registration |
| `alice_handlers.py` | 1,600+ | Commands, callbacks, message routing |
| `alice_keyboards.py` | 250 | Keyboard layouts for all phases |
| `alice_helpers.py` | 380 | Game logic, loops, session management |
| `alice_models.py` | 78 | PlayerState, GameSession data classes |
| `content.py` | 135 | Game content (60 unique trigger messages) |

**Total:** 2,600+ lines of production code

## Design Decisions

### Reliability First

- **Triple Redundancy** — Every action works 3 ways (button → slash command → fallback)
- **ReplyKeyboard Buttons** — More reliable than inline buttons in groups
- **Text-Based Routing** — Group buttons route through message handler (never fails)
- **Error Handling** — All edge cases caught, no user-facing crashes

### No Duplicate Messages

- Lobby message edited in-place (not re-sent)
- Each action produces exactly one message
- No accidental duplicates from state changes

### Unique Content

- 60 unique trigger messages (no repeats)
- 20 early phase, 20 mid phase, 20 late phase
- Each player gets a unique secret
- Oracle responses randomized

---

Made with ❤️ for mystery lovers.
