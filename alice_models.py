"""
alice_models.py — Data models for the Alice Is Missing Telegram bot.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

UTC = timezone.utc
GAME_DURATION_MINUTES = 95


@dataclass
class PlayerState:
    telegram_name: str
    telegram_id: int
    username: str = ""
    character_name: str = "Awaiting name"
    secret: str = ""
    notes: list = field(default_factory=list)
    triggers_sent: int = 0


@dataclass
class GameSession:
    game_id: str
    host_id: int
    lobby_chat_id: int
    host_telegram_name: str = ""
    players: dict = field(default_factory=dict)
    npc_names: list = field(default_factory=list)
    started: bool = False
    ended: bool = False
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    lobby_msg_id: Optional[int] = None
    sus_points: dict = field(default_factory=dict)
    player_tasks: dict = field(default_factory=dict)
    trigger_task: object = None
    reminder_task: object = None
    trigger_inflight: set = field(default_factory=set)

    def is_lobby(self) -> bool:
        return not self.started and not self.ended

    def is_active(self) -> bool:
        return self.started and not self.ended

    def elapsed_minutes(self) -> float:
        if not self.start_time or not self.started:
            return 0.0
        now = datetime.now(tz=UTC)
        # Always compare timezone-aware datetimes
        st = self.start_time
        if st.tzinfo is None:
            st = st.replace(tzinfo=UTC)
        diff = (now - st).total_seconds()
        # Guard against clock skew / future start_time
        return max(0.0, diff / 60.0)

    def remaining_minutes(self) -> float:
        return max(0.0, GAME_DURATION_MINUTES - self.elapsed_minutes())

    def game_phase(self) -> str:
        elapsed = self.elapsed_minutes()
        if elapsed < 30:
            return "early"
        elif elapsed < 65:
            return "mid"
        else:
            return "late"

    def roster_text(self, include_dummies: bool = False) -> str:
        lines = []
        for uid, ps in self.players.items():
            if uid < 0 and not include_dummies:
                continue
            crown = " 👑" if uid == self.host_id else ""
            if ps.character_name == "Awaiting name":
                lines.append(f"⏳ {ps.telegram_name} (setting name…){crown}")
            else:
                prefix = "🤖" if uid < 0 else "👤"
                lines.append(f"{prefix} {ps.character_name}{crown}")
        for npc in self.npc_names:
            lines.append(f"🎭 {npc} (NPC)")
        return "\n".join(lines) if lines else "(no players yet)"

    def all_character_names(self, dev_mode: bool = False) -> list:
        names = []
        for uid, ps in self.players.items():
            if uid < 0 and not dev_mode:
                continue
            if ps.character_name and ps.character_name != "Awaiting name":
                names.append(ps.character_name)
        names.extend(self.npc_names)
        return names

    def pending_real_players(self) -> list:
        return [
            uid for uid, ps in self.players.items()
            if uid >= 0 and ps.character_name == "Awaiting name"
        ]

    def award_sus(self, char_name: str, kind: str) -> None:
        if char_name not in self.sus_points:
            self.sus_points[char_name] = {"in_game": 0, "in_text": 0}
        if kind in ("in_game", "in_text"):
            self.sus_points[char_name][kind] += 1
