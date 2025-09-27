import json
import multiprocessing
import random
import socket
import struct
import time
from collections import Counter

# Import possible actions
from board import (
    CallAction,
    Card,
    CheckAction, # The engine does support check action BUT a call action does the same thing
                 # so to reduce chance of error, i recommend not using CheckAction
    Deck,
    FoldAction,
    RaiseAction,
    evaluate_hand,
)

"""
Poker Bot server
Uses TCP to communicate with engine, expects JSON messages

Since this is a separate process, it can be in any language that can do TCP 
and JSON. And can continue to process when other bots are thinking
"""


def _send_json(conn, obj):
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    conn.sendall(struct.pack(">I", len(data)) + data)


def _recv_json(conn, max_bytes=1 << 20):
    hdr = _recvall(conn, 4)
    if not hdr:
        raise ConnectionError("closed")
    n = struct.unpack(">I", hdr)[0]
    if n > max_bytes:
        raise ValueError("message too large")
    payload = _recvall(conn, n)
    return json.loads(payload.decode("utf-8"))


def _recvall(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed early")
        buf.extend(chunk)
    return bytes(buf)


def _enum_to_wire(a):
    if isinstance(a, FoldAction):
        return {"move": "fold"}
    if isinstance(a, CheckAction):
        return {"move": "check"}
    if isinstance(a, CallAction):
        return {"move": "call"}
    if isinstance(a, RaiseAction):
        return {"move": "raise", "amount": int(a.amount)}
    # safety fallback
    return {"move": "fold"}


class PokerBot(multiprocessing.Process):
    """
    Initialization
    """

    def __init__(self, name="MyBot", host="0.0.0.0", port=5001):
        super().__init__()
        self.running = True
        self.name = name
        self.host = host
        self.port = int(port)
        self.action_count = 0
        self.num_decks = 1  # will be updated when first game state arrives
    
    """
    Starts the bot process.
    Probably shouldn't be messed with...
    """

    def run(self):
        print(f"[{self.name}] Listening on {self.host}:{self.port} ...")
        with socket.create_server((self.host, self.port)) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.settimeout(1.0)  # so we can check self.running
            while self.running:
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    conn.settimeout(5.0)
                    try:
                        req = _recv_json(conn)
                    except Exception:
                        # bad frame or connection issue; ignore this connection
                        continue

                    print(f"Recieved connection with: {req}")
                    op = req.get("op")
                    try:
                        # Handle terminate
                        if op == "terminate":
                            self.running = False
                            _send_json(conn, {"ok": True})
                            print(f"[{self.name}] Terminating on request...")
                            continue

                        # Handle end of round (or start of brand new game)
                        if op == "end":
                            state_obj = req.get("state", {})
                            game_state_json = json.dumps(state_obj, separators=(",", ":"))
                            print(f"\tRecieved end of game state")
                            try:
                                self.end_game(game_state_json)
                            except Exception as e:
                                print(f"[{self.name}] error in end_game: {e}")
                            continue

                        # Handle action request
                        if op == "act":
                            state_obj = req.get("state", {})
                            game_state_json = json.dumps(state_obj, separators=(",", ":"))
                            try:
                                action_enum = self.decide_action(game_state_json)
                            except Exception as e:
                                # Don't let a bot exception kill the connection/process.
                                print(f"[{self.name}] decide_action raised: {e}")
                                action_enum = FoldAction()
                            self.action_count += 1
                            try:
                                _send_json(conn, _enum_to_wire(action_enum))
                            except Exception as e:
                                print(f"[{self.name}] failed to send action: {e}")
                            print(f"\tSending action, {action_enum}")

                        else:
                            print("This is a bad json?")
                            if "state" not in req and len(req) > 0:
                                # Treat entire object as state
                                game_state_json = json.dumps(req, separators=(",", ":"))
                                try:
                                    action_enum = self.decide_action(game_state_json)
                                except Exception as e:
                                    print(f"[{self.name}] decide_action raised: {e}")
                                    action_enum = FoldAction()
                                self.action_count += 1
                                try:
                                    _send_json(conn, _enum_to_wire(action_enum))
                                except Exception as e:
                                    print(f"[{self.name}] failed to send action: {e}")
                            else:
                                try:
                                    _send_json(conn, {"error": "unknown op"})
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"[{self.name}] unexpected error handling request: {e}")
                        # Best effort: try to send a fold action so engine can continue
                        try:
                            _send_json(conn, _enum_to_wire(FoldAction()))
                        except Exception:
                            pass

                time.sleep(0.005)  # be nice to CPU

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
            return CallAction()
        return FoldAction()

    def end_game(self, game_state_json):
        """Handle end of round state. Game state shows final round standings,
        each player's last action, and whether deck needs resetting."""
        game_state = json.loads(game_state_json)
        # Update our view of how many decks are in play
        self.num_decks = game_state.get("num_decks", 1)
        # Reset our deck model if server indicates shuffle
        if game_state.get("reset_deck", False):
            print(f"[{self.name}] Resetting deck ({self.num_decks} decks)")
            self.deck = Deck(self.num_decks)
            self.deck.shuffle()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--name", default="Simple")
    args = ap.parse_args()
    PokerBot(name=args.name, host=args.host, port=args.port).run()
