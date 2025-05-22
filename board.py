import random
from collections import namedtuple
from itertools import combinations

# Card and Deck setup
suits = ["Hearts", "Diamonds", "Clubs", "Spades"]
ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King", "Ace"]
RANK_ORDER = {rank: i for i, rank in enumerate(ranks, start=2)}
hand_score = [
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
]

# Actions for player
FoldAction = namedtuple("FoldAction", [])
CallAction = namedtuple("CallAction", [])
CheckAction = namedtuple("CheckAction", [])
RaiseAction = namedtuple("RaiseAction", ["amount"])


class Card:
    SUIT_MAP = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades"}

    RANK_MAP = {
        "A": "Ace",
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
        "7": "7",
        "8": "8",
        "9": "9",
        "T": "10",
        "J": "Jack",
        "Q": "Queen",
        "K": "King",
    }
    REVERSE_SUIT_MAP = {v: k for k, v in SUIT_MAP.items()}
    REVERSE_RANK_MAP = {v: k for k, v in RANK_MAP.items()}

    def __init__(self, suit, rank):
        if suit not in self.SUIT_MAP.values():
            raise ValueError(f"Invalid suit name: {suit}")
        if rank not in self.RANK_MAP.values():
            raise ValueError(f"Invalid rank name: {rank}")
        self.suit = suit
        self.rank = rank

    def __str__(self):
        return f"{self.rank} of {self.suit}"

    def short_str(self):
        return f"{self.REVERSE_RANK_MAP[self.rank]}{self.REVERSE_SUIT_MAP[self.suit]}"

    @classmethod
    def from_string(cls, short_str):
        if len(short_str) != 2:
            raise ValueError("Card string must be exactly 2 characters")
        rank_char, suit_char = short_str[0], short_str[1]
        if rank_char in cls.RANK_MAP and suit_char in cls.SUIT_MAP:
            return cls(cls.SUIT_MAP[suit_char], cls.RANK_MAP[rank_char])
        raise ValueError(f"Invalid card string: {short_str}")

    def to_dict(self):
        return {"suit": self.suit, "rank": self.rank}


class Deck:
    def __init__(self):
        self.cards = [Card(suit, rank) for suit in suits for rank in ranks]
        self.used_cards = []
        self.community_cards = []

    def shuffle(self):
        self.cards += self.used_cards
        self.used_cards = []
        random.shuffle(self.cards)

    def deal(self, num=1):
        dealt = []
        for _ in range(num):
            if self.cards:
                card = self.cards.pop()
                self.used_cards.append(card)
                dealt.append(card)
            else:
                print("No more cards in the deck.")
        return dealt

    def deal_table(self, num=1):
        self.community_cards += self.deal(num)
        return self.community_cards

    def show_table(self):
        return [str(card) for card in self.community_cards]

    def reset(self):
        self.community_cards = []


def evaluate_hand(cards):
    def card_rank(card):
        return RANK_ORDER[card.rank]

    def is_flush(hand):
        suits = [card.suit for card in hand]
        return len(set(suits)) == 1

    def is_straight(ranks):
        ranks = sorted(set(ranks))
        if ranks == [2, 3, 4, 5, 14]:  # A-2-3-4-5
            return True, 5
        for i in range(len(ranks) - 4 + 1):
            if ranks[i : i + 5] == list(range(ranks[i], ranks[i] + 5)):
                return True, ranks[i + 4]
        return False, None

    def group_by_rank(ranks):
        count = {}
        for r in ranks:
            count[r] = count.get(r, 0) + 1
        return sorted(count.items(), key=lambda x: (-x[1], -x[0]))

    best_hand = None
    best_score = (0, [])

    for combo in combinations(cards, 5):
        ranks = [card_rank(card) for card in combo]
        flush = is_flush(combo)
        straight, high_straight = is_straight(ranks)
        grouped = group_by_rank(ranks)
        rank_counts = [x[1] for x in grouped]
        top_ranks = [x[0] for x in grouped]

        if flush and straight:
            score = (8, [high_straight])
        elif 4 in rank_counts:
            score = (7, top_ranks)
        elif 3 in rank_counts and 2 in rank_counts:
            score = (6, top_ranks)
        elif flush:
            score = (5, sorted(ranks, reverse=True))
        elif straight:
            score = (4, [high_straight])
        elif 3 in rank_counts:
            score = (3, top_ranks)
        elif rank_counts.count(2) == 2:
            score = (2, top_ranks)
        elif 2 in rank_counts:
            score = (1, top_ranks)
        else:
            score = (0, sorted(ranks, reverse=True))

        if score > best_score:
            best_score = score
            best_hand = combo

    return best_score, best_hand


class GameState:
    def __init__(self, deck=[], players=[], ante=0):
        self.deck = deck
        self.players = players
        self.pot = 0
        self.curr_bet = 0
        self.ante = ante

    def to_safe_dict(self):
        d = {}
        d["board"] = [x.to_dict() for x in self.deck.community_cards]
        d["pot"] = self.pot
        d["curr_bet"] = self.curr_bet
        d["ante"] = self.ante
        players_dict = {}
        i = 0
        for player in self.players:
            pd = {}
            pd["chips"] = player.chips
            pd["action"] = "NULL"
            pd["position"] = i
            i += 1
            players_dict[player.name] = pd
        d["players"] = players_dict
        return d

    def to_end_dict(self):
        d = {}
        d["is_end_state"] = True
        d["board"] = [x.to_dict() for x in self.deck.community_cards]
        d["pot"] = self.pot
        d["ante"] = self.ante
        players_dict = {}
        i = 0
        for player in self.players:
            pd = {}
            pd["chips"] = player.chips
            pd["action"] = player.last_action
            pd["position"] = i
            i += 1
            if player.in_hand:
                pd["hand"] = [x.short_str() for x in player.hand]
            else:
                pd["hand"] = []
            players_dict[player.name] = pd
        d["players"] = players_dict
        return d

    def reset_turn(self):
        self.curr_bet = 0
        for p in self.players:
            p.ready = False
            p.curr_bet = 0

    def reset_round(self, ante=0, blinds=[0, 0]):
        self.ante = ante
        self.pot = 0
        self.reset_turn()
        blind_count = 0
        for p in self.players:
            if p.chips >= ante:
                p.chips -= ante

                if blind_count == 0 and p.chips >= blinds[0]:
                    p.chips -= blinds[0]
                    self.pot += blinds[0]
                    blind_count += 1
                if blind_count == 1 and p.chips >= blinds[1]:
                    p.chips -= blinds[1]
                    self.pot += blinds[1]
                    blind_count += 1

                p.in_hand = True
                self.pot += ante
                continue
            p.in_hand = False
