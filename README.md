# Alice Is Missing - Telegram Bot

An unofficial Telegram adaptation of the silent mystery roleplaying game *Alice Is Missing*. Players uncover what happened to Alice through timed trigger cards, private messages, clues, and suspicion tracking.

## What The Game Is

This is a text-only story game for a group chat and private DMs.

- One player hosts the game from the group.
- Players join from the lobby, set their character names, and stay in character.
- The bot sends secrets, clue card reminders and prompts over the course of the session.
- Suspicion points, notes, and private messages help shape the story as it unfolds.

## How It Plays
https://docs.google.com/document/d/e/2PACX-1vSFwZrJL02xuBbWOm5THFvpRCR4KFh9t9-J60gEZHJt8LPJ0kEktHfuFCN7ANnQqWkkBLXavoSLGSDS/pub
1. The host creates a lobby with `/newgame`.
2. Players join from the pinned group card.
3. Each player sets a character name in DM.
4. The host starts the game with `/startgame`.
5. The bot runs the session with trigger cards, clue reminders, and timed prompts.
6. When the story reaches its end, the host closes the session with `/endgame`.

## Main Features

- Lobby and live-game group cards with phase-aware buttons
- Private DM tools for notes, messaging, and divine fate
- Host-only suspicion tracking and character management
- Trigger cards and reminders driven by game time
- Dev mode for testing without a full table

## Commands

### Group

- `/newgame` - Create a new lobby
- `/characterlist` - Show the roster
- `/showsus` - Show suspicion points
- `/status` - Show the current game state

### Private DM

- `/start` - Open the bot chat
- `/join GAMEID` - Join a lobby
- `/name NAME` - Set or change your character name
- `/message` - Message another player
- `/notes` - Open your notes
- `/fate` - Ask divine fate
- `/guide` - Show the game guide

### Host Only

- `/startgame` - Begin the session
- `/endgame` - End the session
- `/sus` - Award suspicion points
- `/addnpc` - Add an NPC
- `/sendguide` - Send the guide to the group
- `/sendcharlist` - Send the roster to the group
- `/postsus` - Send the suspicion table to the group

### Dev

- `/dev alice` - Toggle test mode for local development

## Setup

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
python main.py
```

## Attribution

This project is an unofficial fan adaptation based on *Alice Is Missing*. The original game, name, and related intellectual property belong to their respective creators and rights holders. If you plan to reuse any original game material, check the original license and usage terms first.
