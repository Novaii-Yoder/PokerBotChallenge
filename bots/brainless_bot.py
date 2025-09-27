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

    """
    Decides action bot wants to take
    @param game_state_json: json containing relavant info on the game.
    
    @return action: either CallAction(), RaiseAction(amount), FoldAction(),
    """

    def decide_action(self, game_state_json):
        game_state = json.loads(game_state_json)

        player_curr_bet = game_state.get("player_curr_bet", 0)
        board = game_state.get("board", [])
        board = [Card(suit=x["suit"], rank=x["rank"]) for x in board]
        hand = game_state.get("hand", [])
        hand = [Card(suit=x["suit"], rank=x["rank"]) for x in hand]
        can_check = game_state.get("can_check", False)
        curr_bet = game_state.get("curr_bet", 0)
        pot = game_state.get("pot", 0)
        players = game_state.get("players", {})
        player_stack = players.get(self.name, {}).get("chips", 0)
        big_blind = game_state.get("big_blind", 0)
        small_blind = game_state.get("small_blind", 0)

        # always commit, never re-raise
        if player_curr_bet > 0:
            return CallAction()

        # Dummy logic
        if random.randint(0, 100) > 50:
            return RaiseAction(curr_bet + int(random.randint(0, player_stack)))
        else:
            return CallAction()
        pass

    def end_game(self, game_state_json):
        # Handle end of round state
        # game state will show final round standings and each
        # players last action
        pass


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5002)
    ap.add_argument("--name", default="Brainless")
    args = ap.parse_args()
    PokerBot(name=args.name, host=args.host, port=args.port).run()
