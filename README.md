# Alice Is Missing - Telegram Bot

An unofficial Telegram adaptation of the silent mystery roleplaying game *Alice Is Missing*. Players uncover what happened to Alice through timed trigger cards, private messages, clues, and suspicion tracking.

## ⚠️ Self-Hosting Required

**This bot is not available as a public service.** To use it, you must run your own instance by following the setup instructions below. I cannot maintain a 24/7 hosted version for public use.

## What The Game Is

This is a text-only story game for a group chat and private DMs.

- One player hosts the game from the group.
- Players join from the lobby, set their character names, and stay in character.
- The bot sends secrets, clue card reminders and prompts over the course of the session.
- Suspicion points, notes, and private messages help shape the story as it unfolds.

## How It Plays

[Full Game Guide](https://docs.google.com/document/d/e/2PACX-1vSFwZrJL02xuBbWOm5THFvpRCR4KFh9t9-J60gEZHJt8LPJ0kEktHfuFCN7ANnQqWkkBLXavoSLGSDS/pub)

1. The host creates a lobby with `/newgame`.
2. Players join from the pinned group card.
3. Each player sets a character name in DM.
4. The host starts the game with `/startgame`.
5. The bot runs the session with trigger cards, clue reminders, and timed prompts.
6. When the story reaches its end, the host closes the session with `/endgame`.

## Running Your Own Bot

### Step 1: Create a Telegram Bot

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the prompts
3. Save your bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### Step 2: Clone This Repository

```bash
git clone https://github.com/k4nap3s/Alice-Telegram-Bot.git
cd Alice-Telegram-Bot
```

### Step 3: Choose a Hosting Method

#### Option A: Local Hosting (Free)

**Best for:** Running the bot during game sessions on your own computer

**Requirements:** Python 3.11+

```bash
# Install dependencies
pip install -r requirements.txt

# Set your bot token
export TELEGRAM_BOT_TOKEN="your_token_here"

# Run the bot
python3 main.py
```

The bot will run as long as your terminal is open. Press `Control+C` to stop it.

**Note:** Your computer must be on and connected to the internet for the bot to work.

#### Option B: Cloud Hosting ($5-7/month)

**Best for:** 24/7 availability without keeping your computer running

**Recommended platforms:**
- [Render](https://render.com) - Background Worker ($7/month)
- [Railway](https://railway.app) - Pay-as-you-go (typically $5-10/month)
- [PythonAnywhere](https://pythonanywhere.com) - Web App ($5/month)

Each platform has different deployment steps. See their documentation for Python bot deployment.

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

## Attribution

This project is an unofficial fan adaptation based on *Alice Is Missing*. The original game, name, and related intellectual property belong to their respective creators and rights holders. If you plan to reuse any original game material, check the original license and usage terms first.
