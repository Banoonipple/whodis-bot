"""
Game engine for "Who Dis?" — an Apples-to-Apples-style party game.

Everything here is pure game state / logic, with no Discord dependencies,
so it's easy to reason about and test independently of the bot layer.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(__file__).parent / "data"

HAND_SIZE = 7


def load_deck() -> dict:
    path = DATA_DIR / "deck.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build_card_pools():
    """Returns (inbox_cards, reply_cards) lists of dicts."""
    deck = load_deck()
    return deck["inbox"], deck["replies"]


@dataclass
class Player:
    user_id: int
    name: str
    hand: List[dict] = field(default_factory=list)
    score: int = 0
    is_bot: bool = False


@dataclass
class Submission:
    player_id: int
    card: dict


class GameError(Exception):
    """Raised for invalid game actions (wrong phase, not your turn, etc.)."""


class WhoDisGame:
    PHASE_LOBBY = "lobby"
    PHASE_COLLECTING = "collecting"
    PHASE_JUDGING = "judging"
    PHASE_FINISHED = "finished"

    def __init__(self, host_id: int, points_to_win: int = 5):
        if points_to_win not in (3, 5, 7, 10):
            raise ValueError("points_to_win must be one of 3, 5, 7, 10")

        self.host_id = host_id
        self.points_to_win = points_to_win

        self.players: Dict[int, Player] = {}
        self.phase = self.PHASE_LOBBY

        self.inbox_draw: List[dict] = []
        self.inbox_discard: List[dict] = []
        self.reply_draw: List[dict] = []
        self.reply_discard: List[dict] = []

        self.judge_order: List[int] = []  # player ids in judging rotation order
        self.judge_index: int = 0

        self.current_inbox: Optional[dict] = None
        self.submissions: Dict[int, Submission] = {}
        self.round_number: int = 0
        self.winner_id: Optional[int] = None
        self.last_round_result: Optional[dict] = None  # for announcements

    # ---------- Lobby management ----------

    def add_player(self, user_id: int, name: str) -> None:
        if self.phase != self.PHASE_LOBBY:
            raise GameError("The game has already started — you can't join mid-round.")
        if user_id in self.players:
            raise GameError("You're already in this game.")
        if len(self.players) >= 20:
            raise GameError("This game is full (20 players max).")
        self.players[user_id] = Player(user_id=user_id, name=name)

    def remove_player(self, user_id: int) -> None:
        self.players.pop(user_id, None)

    def player_count(self) -> int:
        return len(self.players)

    # ---------- Game start ----------

    def start(self) -> None:
        if self.phase != self.PHASE_LOBBY:
            raise GameError("This game has already started.")
        if len(self.players) < 3:
            raise GameError("You need at least 3 players to start.")

        inbox_cards, reply_cards = build_card_pools()
        self.inbox_draw = inbox_cards[:]
        self.reply_draw = reply_cards[:]
        random.shuffle(self.inbox_draw)
        random.shuffle(self.reply_draw)

        # Deal hands
        for player in self.players.values():
            player.hand = [self._draw_reply() for _ in range(HAND_SIZE)]

        # Randomize judge order
        self.judge_order = list(self.players.keys())
        random.shuffle(self.judge_order)
        self.judge_index = 0

        self._begin_round()

    def _begin_round(self) -> None:
        self.round_number += 1
        self.submissions = {}
        self.current_inbox = self._draw_inbox()
        self.phase = self.PHASE_COLLECTING
        self.last_round_result = None

    # ---------- Draw pile helpers ----------

    def _draw_inbox(self) -> dict:
        if not self.inbox_draw:
            if not self.inbox_discard:
                raise GameError("No Inbox cards left in any pile.")
            self.inbox_draw, self.inbox_discard = self.inbox_discard, []
            random.shuffle(self.inbox_draw)
        return self.inbox_draw.pop()

    def _draw_reply(self) -> dict:
        if not self.reply_draw:
            if not self.reply_discard:
                raise GameError("No Reply cards left in any pile.")
            self.reply_draw, self.reply_discard = self.reply_discard, []
            random.shuffle(self.reply_draw)
        return self.reply_draw.pop()

    # ---------- Judge helpers ----------

    def current_judge_id(self) -> int:
        return self.judge_order[self.judge_index % len(self.judge_order)]

    def is_judge(self, user_id: int) -> bool:
        return self.phase in (self.PHASE_COLLECTING, self.PHASE_JUDGING) and user_id == self.current_judge_id()

    def non_judge_players(self) -> List[Player]:
        judge_id = self.current_judge_id()
        return [p for uid, p in self.players.items() if uid != judge_id]

    # ---------- Submissions ----------

    def submit_reply(self, user_id: int, card_id: str) -> None:
        if self.phase != self.PHASE_COLLECTING:
            raise GameError("Submissions aren't open right now.")
        if user_id not in self.players:
            raise GameError("You're not in this game.")
        if self.is_judge(user_id):
            raise GameError("You're the Judge this round — you don't submit a reply.")
        if user_id in self.submissions:
            raise GameError("You've already submitted a reply this round.")

        player = self.players[user_id]
        card = next((c for c in player.hand if c["id"] == card_id), None)
        if card is None:
            raise GameError("That card isn't in your hand (maybe you already played it).")

        player.hand.remove(card)
        self.submissions[user_id] = Submission(player_id=user_id, card=card)

        if len(self.submissions) == len(self.non_judge_players()):
            self.phase = self.PHASE_JUDGING

    def all_submitted(self) -> bool:
        return len(self.submissions) == len(self.non_judge_players())

    def anonymized_submissions(self) -> List[Submission]:
        """A shuffled, judge-facing view of submissions (owner hidden by list order)."""
        subs = list(self.submissions.values())
        random.shuffle(subs)
        return subs

    # ---------- Judging ----------

    def judge_pick(self, judge_id: int, winning_card_id: str) -> dict:
        if self.phase != self.PHASE_JUDGING:
            raise GameError("Judging isn't open yet — not everyone has submitted.")
        if judge_id != self.current_judge_id():
            raise GameError("Only the current Judge can pick the winner.")

        winning_sub = next((s for s in self.submissions.values() if s.card["id"] == winning_card_id), None)
        if winning_sub is None:
            raise GameError("That card wasn't submitted this round.")

        winner = self.players[winning_sub.player_id]
        winner.score += 1

        # Discard the inbox card and all submitted replies, refill hands
        self.inbox_discard.append(self.current_inbox)
        for sub in self.submissions.values():
            self.reply_discard.append(sub.card)
            p = self.players.get(sub.player_id)
            if p is not None:
                p.hand.append(self._draw_reply())

        result = {
            "round_number": self.round_number,
            "inbox": self.current_inbox,
            "winning_card": winning_sub.card,
            "winner_id": winner.user_id,
            "winner_name": winner.name,
            "winner_score": winner.score,
        }
        self.last_round_result = result

        if winner.score >= self.points_to_win:
            self.phase = self.PHASE_FINISHED
            self.winner_id = winner.user_id
        else:
            self.judge_index += 1
            self._begin_round()

        return result

    # ---------- Misc ----------

    def scoreboard(self) -> List[Player]:
        return sorted(self.players.values(), key=lambda p: (-p.score, p.name.lower()))
