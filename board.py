import contextlib
import copy
import random
import socket
from collections import namedtuple
from itertools import combinations

from netwire import send_json

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
CallAction = namedtuple("CallAction", []) # call == check if no current bet
CheckAction = namedtuple("CheckAction", [])
RaiseAction = namedtuple("RaiseAction", ["amount"])

"""
Card obj
"""


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
        if suit in self.REVERSE_SUIT_MAP:
            pass
        elif suit in self.SUIT_MAP:
            suit = self.SUIT_MAP[suit]
        else:
            raise ValueError(f"Invalid suit name: {suit}")

        if rank in self.REVERSE_RANK_MAP:
            pass
        elif rank in self.RANK_MAP:
            rank = self.RANK_MAP[rank]
        else:
            raise ValueError(f"Invalid rank name: {rank}")

        self.suit = suit
        self.rank = rank

    def __str__(self):
        return f"{self.rank} of {self.suit}"

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        if not isinstance(other, Card):
            return False
        return self.suit == other.suit and self.rank == other.rank

    def __ne__(self, other):
        result = self.__eq__(other)
        return not result

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


"""
Deck obj
Contains methods for shuffling, dealing, and managing multiple decks.

* Copy and import this for your bots to keep track of possible cards left. *
"""


class Deck:
    def __init__(self, num_decks: int = 1):
        self.num_decks = max(1, int(num_decks))
        self.cards = self._fresh_cards()
        self.used_cards = []
        self.community_cards = []

    def _fresh_cards(self):
        return [
            Card(suit, rank)
            for _ in range(self.num_decks)
            for suit in suits
            for rank in ranks
        ]

    def shuffle(self):
        self.cards += self.used_cards
        self.used_cards = []
        random.shuffle(self.cards) # TODO: custom shuffle

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

    def burn(self, num=1):
        for _ in range(num):
            if self.cards:
                card = self.cards.pop()
                self.used_cards.append(card)
            else:
                print("No more cards in the deck.")
                return False
        return True

    def deal_table(self, num=1):
        dealt = []
        for _ in range(num):
            if self.cards:
                card = self.cards.pop()
                dealt.append(card)
            else:
                print("No more cards in the deck.")
        self.community_cards += dealt
        return self.community_cards
        return self.community_cards

    def show_table(self):
        return [str(card) for card in self.community_cards]

    def reset(self):
        self.cards = self._fresh_cards()
        self.used_cards = []
        self.community_cards = []
    
    # check if deck needs resetting
    def verify(self, num_players):
        total_cards = 52 * self.num_decks
        if len(self.cards) + len(self.used_cards) + len(self.community_cards) != total_cards:
            print("Deck inconsistency detected. Resetting deck.")
            self.reset()
            self.shuffle()
            return True
        if len(self.cards) < num_players * 2 + 5 + 3:  # 2 per player + 5 community + 3 burn
            print("Deck low on cards. Resetting deck.")
            self.reset()
            self.shuffle()
            return True
        return False
        


"""
Evaluates the best possible hand from a set of cards
only works with a set of more than 5 cards

@param cards: a list of cards, is both hand and community cards

@return best_score: int of score
@return best_hand: list containing ranks of best hand
"""


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
        if ranks[0:5] == list(range(ranks[0], ranks[0] + 5)):
            return True, ranks[4]
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

"""
Helper to terminate a bot process via TCP
"""


def _terminate_bot(host, port, timeout=1.0):
    """Politely tell a TCP bot to exit; ignore if it’s already gone."""
    try:
        with contextlib.closing(
            socket.create_connection((host, port), timeout=timeout)
        ) as s:
            pass
            send_json(s, {"op": "terminate"})
    except OSError:
        pass


"""
Game state obj
"""


class GameState:
    def __init__(self, deck=[], players=[]):
        self.deck = deck
        self.players = players
        self.pot = 0
        self.curr_bet = 0
        self.small_blind = 0
        self.big_blind = 0

    def to_safe_dict(self):
        d = {}
        d["board"] = [x.to_dict() for x in self.deck.community_cards]
        # expose deck size so bots can reason about remaining cards / counting
        d["num_decks"] = self.deck.num_decks if hasattr(self.deck, "num_decks") else 1
        d["pot"] = self.pot
        d["curr_bet"] = self.curr_bet
        d["small_blind"] = self.small_blind
        d["big_blind"] = self.big_blind
        players_dict = {}
        i = 0
        for player in self.players:
            pd = {}
            pd["chips"] = player.chips
            pd["last_action"] = player.last_action
            pd["position"] = i
            i += 1
            players_dict[player.name] = pd
        d["players"] = players_dict
        return d

    # This is sent to bots at end of each hand, and very start of game (for bot deck setup)
    def to_end_dict(self, winners, curr_player, reset_deck=False):
        d = {}
        d["is_end_state"] = True
        d["board"] = [x.to_dict() for x in self.deck.community_cards]
        d["num_decks"] = self.deck.num_decks if hasattr(self.deck, "num_decks") else 1
        d["reset_deck"] = reset_deck
        d["pot"] = self.pot
        d["small_blind"] = self.small_blind
        d["big_blind"] = self.big_blind
        players_dict = {}
        i = 0
        for player in self.players:
            pd = {}
            if player.name in winners:
                pd["winner"] = True
            else:
                pd["winner"] = False

            pd["chips"] = player.chips
            pd["last_action"] = player.last_action
            pd["position"] = i
            i += 1
            if player.in_hand or curr_player == player.name:
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

    def reset_round(self, blinds=[0, 0]):
        assert (
            isinstance(blinds, list) and len(blinds) == 2
        ), "Blinds must be of form [X, Y]"
        self.pot = 0
        self.reset_turn()
        self.small_blind = blinds[0]
        self.big_blind = blinds[1]
        blind_count = 0
        for p in self.players:
            # First check if player can even afford blinds
            if p.chips < blinds[1]:  # Can't afford BB
                print(f"{p.name} can't afford big blind ({p.chips} < {blinds[1]}), sitting out")
                p.in_hand = False
                #TODO: should bot be terminated? removed from players
                continue
            
            # Now pay blinds
            if blind_count == 1:  # Big blind
                print(f"{p.name} pays big blind of {blinds[1]}")
                p.chips -= blinds[1]
                self.pot += blinds[1]
                p.curr_bet = blinds[1]
                self.curr_bet = blinds[1]
                blind_count += 1
                p.in_hand = True
            elif blind_count == 0:  # Small blind
                if p.chips >= blinds[0]:
                    print(f"{p.name} pays small blind of {blinds[0]}")
                    p.chips -= blinds[0]
                    self.pot += blinds[0]
                    p.curr_bet = blinds[0]
                    self.curr_bet = blinds[0]
                    blind_count += 1
                    p.in_hand = True
                else:
                    print(f"{p.name} can't afford small blind ({p.chips} < {blinds[0]}), sitting out")
                    p.in_hand = False
            else:  # Not in blind
                p.in_hand = True
        i = 0
        while i < len(self.players):
            p = self.players[i]
            if p.chips <= 0:
                print(f"Eliminated player {p.name}")
                # lets not terminate bots for now
                #_terminate_bot(p.host, p.port, timeout=1.0)
                self.players.pop(i)
                continue
            i += 1


########### Visual ascii art printing.


"""
Prints a list of cards as ascii art poker cards.

@param cards: a list of card objs
"""


def print_cards_as_ascii(cards):
    suit_map = {"H": "♡", "S": "♤", "C": "♧", "D": "♢"}

    rank_suits = []
    for card in cards:
        card = card.short_str()
        rank = card[0]
        if rank == "T":
            rank = "10"

        suit = suit_map[card[1]]
        rank_suits.append((rank, suit))

    for i in range(7):
        for j in range(len(rank_suits)):
            rank, suit = rank_suits[j]
            string = "   "

            if rank == "10":
                string = "10" + suit
            else:
                string = rank + suit + " "

            if i == 0:
                print(f"╔═════════╗", end="  ")
            elif i == 1:
                print(f"║{string}      ║", end="  ")
            elif i == 5:
                print(f"║      {string}║", end="  ")
            elif i == 6:
                print(f"╚═════════╝", end="  ")
            else:
                print(f"║         ║", end="  ")
        print()
