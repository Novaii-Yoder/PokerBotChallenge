import json
import multiprocessing
import random
import time

# Import possible actions
from board import CallAction, CheckAction, FoldAction, RaiseAction

"""
Poker Bot obj
@inherits multiprocessing.Process
Allows the bot to 'think' while other players wait on action
"""


class PokerBot(multiprocessing.Process):
    """
    Initialization
    """

    def __init__(self, conn, name="MyBot"):
        super().__init__()
        self.conn = conn
        self.running = True
        self.name = name

    """
    Starts the bot process.
    Probably shouldn't be messed with...
    """

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

    """
    Decides action bot wants to take
    @param game_state_json: json containing relavant info on the game.
    
    @return action: either CallAction(), RaiseAction(amount), FoldAction(),
    """

    def decide_action(self, game_state_json):
        game_state = json.loads(game_state_json)

        player_curr_bet = game_state.get("player_curr_bet", 0)
        player_stack = game_state.get("player_stack", 0)
        community_cards = game_state.get("community_cards", [])
        hand = game_state.get("hand", [])
        can_check = game_state.get("can_check", False)
        curr_bet = game_state.get("curr_bet", 0)

        # always commit, never re-raise
        if player_curr_bet > 0:
            return CallAction()

        # Dummy logic
        if random.randint(0, 100) > 50:
            return RaiseAction(curr_bet + random.randint(1, 10) * (player_stack // 28))
        else:
            return CallAction()
        pass

    def end_game(self, game_state_json):
        # Handle end of round state
        # game state will show final round standings and each
        # players last action
        pass
