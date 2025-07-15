import json
import multiprocessing
import random
import time
from collections import Counter

# Import possible actions
from board import (
    CallAction,
    Card,
    CheckAction,
    Deck,
    FoldAction,
    RaiseAction,
    evaluate_hand,
)

"""
Jacob Yoder
5/20/2025

A very simple bot that can evaluate a couple hand types and makes safe bets.

Needs:
    straight logic
    full house logic
    predicting other players hands?
"""


class PokerBot(multiprocessing.Process):
    def __init__(self, conn, name="MyBot"):
        super().__init__()
        self.conn = conn
        self.running = True
        self.name = name
        self.action_count = 0

    def run(self):
        print(f"[{self.name}] Starting bot process...")
        while self.running:
            if self.conn.poll():  # Check for incoming message
                msg = self.conn.recv()
                if msg == "terminate":
                    self.running = False
                    print(f"[{self.name}] Terminating bot process...")
                else:
                    # Assume msg is the game state JSON
                    action = self.decide_action(msg)
                    self.conn.send(action)
            time.sleep(0.01)  # Prevent CPU overuse

    def decide_action(self, game_state_json):
        self.action_count += 1
        game_state = json.loads(game_state_json)
        is_end_state = game_state.get("is_end_state", False)
        if is_end_state:
            self.end_game(game_state_json)

        player_curr_bet = game_state.get("player_curr_bet", 0)
        board = game_state.get("board", [])
        board = [Card(suit=x["suit"], rank=x["rank"]) for x in board]
        hand = game_state.get("hand", [])
        hand = [Card(suit=x["suit"], rank=x["rank"]) for x in hand]
        can_check = game_state.get("can_check", False)
        curr_bet = game_state.get("curr_bet", 0)
        pot = game_state.get("pot", 0)
        players = game_state.get("players", {})
        player_stack = players[self.name]["chips"]
        big_blind = game_state.get("big_blind", 0)
        small_blind = game_state.get("small_blind", 0)

        deck = Deck()
        deck_left = deck.cards
        for card in hand + board:
            deck_left.remove(card)
        draws_left = 5 - len(board)

        ############
        if pot > 0:
            pot_odds = curr_bet / (pot + curr_bet - player_curr_bet)
        else:
            pot_odds = 1

        def flush_odds(hand, board):
            all_cards = hand + board
            suits = [card.suit for card in all_cards]
            suit_counts = Counter(suits)

            deck_suits = [card.suit for card in deck_left]
            deck_suit_counts = Counter(deck_suits)

            max_chance = 0

            for suit, count in suit_counts.items():
                if count == 5:
                    return 1
                # estimated chances of getting needed cards
                chance = (deck_suit_counts[suit] / len(deck_left)) ** (5 - count)
                if chance > max_chance:
                    max_chance = chance
            return chance

        # TODO: Challenge for the builder
        def straight_odds(hand, board):
            all_cards = hand + board

            max_chance = 0

            return max_chance

        def pair_odds(hand, board):
            all_cards = hand + board
            ranks = [card.rank for card in all_cards]
            rank_counts = Counter(ranks)

            deck_ranks = [card.rank for card in deck_left]
            deck_rank_counts = Counter(deck_ranks)

            for rank, count in rank_counts.items():
                if count == 2:
                    return 1

            return 0.5

        def three_odds(hand, board):
            all_cards = hand + board
            ranks = [card.rank for card in all_cards]
            rank_counts = Counter(ranks)

            deck_ranks = [card.rank for card in deck_left]
            deck_rank_counts = Counter(deck_ranks)

            max_rank = []
            max_count = 0
            for rank, count in rank_counts.items():
                if count == 3:
                    return 1
                if count > max_count:
                    max_count = count
                    max_rank.append(rank)
                if count == max_count:
                    max_rank.append(rank)
            odd = 0
            for rank in max_rank:
                odd += (deck_rank_counts[rank] / len(deck_left)) ** (3 - max_count)
            return 1 - ((1 - odd) ** draws_left)

        def quad_odds(hand, board):
            all_cards = hand + board
            ranks = [card.rank for card in all_cards]
            rank_counts = Counter(ranks)

            deck_ranks = [card.rank for card in deck_left]
            deck_rank_counts = Counter(deck_ranks)

            max_rank = []
            max_count = 0
            for rank, count in rank_counts.items():
                if count == 4:
                    return 1
                if count > max_count:
                    max_count = count
                    max_rank.append(rank)
                if count == max_count:
                    max_rank.append(rank)
            odd = 0
            for rank in max_rank:
                odd += (deck_rank_counts[rank] / len(deck_left)) ** (4 - max_count)
            return 1 - ((1 - odd) ** draws_left)

        # very hard to read logic
        # but basically if hand has OK odds or has a decent hand already, raise, otherwise call.
        # if hand has low odds and doesn't already have a ok hand, fold if bet was raised at all.

        if draws_left <= 2:
            score = evaluate_hand(board + hand)[0][0]
            if score > 2:
                if score > 4:
                    # print("has good hand")
                    if curr_bet < player_stack // 2:
                        return RaiseAction(player_stack // 2)
                    return CallAction()
                # print("has ok hand")
                if int(curr_bet * 0.5) < player_stack // 2:
                    RaiseAction(int(curr_bet * 0.5))
                return CallAction()
            # print(f"in last draws, score = {score}, draws = {draws_left}")
            if draws_left == 0 and score >= 1:
                return CallAction()

        if player_stack < big_blind * 2:
            # print("desperate all in")
            return CallAction()
        if (
            flush_odds(hand, board) <= 0.5
            and three_odds(hand, board) <= 0.4
            and draws_left <= 1
        ):
            # print("bad odds")
            if curr_bet - player_curr_bet == 0:
                return CallAction()
            return FoldAction()
        if (
            flush_odds(hand, board) >= 0.5
            or three_odds(hand, board) >= 0.6
            or quad_odds(hand, board) >= 0.2
        ):
            # print("good odds")
            if player_stack // 10 > curr_bet:
                return RaiseAction(player_stack // 10)
            if player_stack > curr_bet - player_curr_bet:
                return CallAction()
        if curr_bet - player_curr_bet <= player_stack // 10 or draws_left >= 2:
            # print("small bet, calling")
            return CallAction()
        # print(f"curr_bet: {curr_bet}, player_curr_bet: {player_curr_bet}")
        # print("############### Bot is confuzed")
        return FoldAction()

    def end_game(self, game_state_json):
        # Handle end of round state
        # game state will show final round standings and each
        # players last action
        pass
