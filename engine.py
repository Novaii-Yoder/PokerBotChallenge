import importlib.util
import json
import multiprocessing
import os
import random
import time
from operator import attrgetter

from board import *

"""
Jacob Yoder
5/29/2025

The engine for a poker bot tournament.

Needs:
    Needs full deck usage, to allow counting cards
    Multi-deck implementation to help balance counting card odds
    Could use split pots
    Full tourney hosting (brackets, stages, and eliminations)
    maybe add function that slows things down for viewing pleasure
"""


"""
Player obj: used for engine side only
"""


class Player:
    def __init__(self, name="bot", bot=None, conn=None, chips=100):
        self.name = name
        self.hand = []
        self.bot = bot
        self.conn = conn
        self.in_hand = True
        self.chips = chips
        self.last_action = None
        self.curr_bet = 0
        self.ready = False

    def receive_cards(self, cards):
        self.hand.extend(cards)

    def show_hand(self):
        return [str(card) for card in self.hand]

    def action(self, game_state):
        if self.conn:
            return self.conn.send(game_state)
        return FoldAction()


"""
Loads players from folder

@param folder_path: location of folder containing bots
@param starting_chips: the chip starting amount for players
@param players_max: the number of players at the table

@return players: list of initialized player objs 
"""


def load_players_from_folder(folder_path, starting_chips=100, players_max=5):
    players = []
    i = 0
    for filename in os.listdir(folder_path):
        if i == 5:
            break
        if filename.endswith(".py"):
            module_name = filename[:-3]
            file_path = os.path.join(folder_path, filename)
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "PokerBot"):
                bot_class = getattr(module, "PokerBot")
                p_conn, b_conn = multiprocessing.Pipe()
                if bot := bot_class(b_conn, name=module_name):
                    bot.start()
                    print(f"CREATED BOT {module_name}")
                    i += 1
                    players.append(
                        Player(
                            bot=bot, conn=p_conn, name=module_name, chips=starting_chips
                        )
                    )

    return players


"""
Evaluates the state of the game and selects winners.

@param players: list of all player objs
@param community_cards: the cards on the table

@return winners: list of winning players
@return best_score: the score of the winning players
"""


def compare_players(players, community_cards):
    best_score = (-1, [])
    winners = []

    for player in players:
        if not player.in_hand:
            continue
        score, hand = evaluate_hand(player.hand + community_cards)
        print(
            f"{player.name}'s best hand: {[str(card) for card in hand]} with score {score}"
        )
        if score > best_score:
            best_score = score
            winners = [player]
        elif score == best_score:
            winners.append(player)

    return winners, best_score


"""
Defines a single round of betting, lets all players decide an action, if there is any mistakes auto-folds

@param players: list of players
@param game_state: GameState obj, defining board, deck, and state
"""


def betting_round(players, game_state, max_time=5):
    def fold(player):
        player.last_action = FoldAction()
        player.in_hand = False

    while players_not_ready(players):
        for player in players:
            if player.ready:
                continue
            if player.in_hand:
                gs = game_state.to_safe_dict()
                gs["hand"] = [x.to_dict() for x in player.hand]
                gs["player_curr_bet"] = player.curr_bet
                player.action(json.dumps(gs))
                start_time = time.perf_counter()
                skip = False
                while not player.conn.poll():
                    if time.perf_counter() - start_time >= max_time:
                        skip = True
                        break
                    time.sleep(0.01)
                if not skip:
                    action = player.conn.recv()
                else:
                    action = FoldAction()
                print(f"{player.name}: {action}")
            else:
                print(f"{player.name}: Not in Round")
                continue

            match action:
                case CheckAction():  # Is this same as call, but bet = 0?
                    if player.curr_bet == game_state.curr_bet:
                        player.last_action = action
                        player.ready = True
                    else:
                        print("Bad check, folding")
                        fold(player)
                    continue

                case CallAction():  ### Add split pots?
                    # print(
                    #    f"p.chips {player.chips}\ng.bet {game_state.curr_bet}\np.bet {player.curr_bet}"
                    # )
                    if player.chips >= game_state.curr_bet - player.curr_bet:
                        game_state.pot += game_state.curr_bet - player.curr_bet
                        player.chips = player.chips - (
                            game_state.curr_bet - player.curr_bet
                        )
                        player.curr_bet = game_state.curr_bet
                        player.last_action = action
                        player.ready = True
                    else:
                        # Forced to go all in
                        player.curr_bet += player.chips
                        game_state.pot += player.chips
                        player.chips = 0
                        player.last_action = action
                        player.ready = True

                        continue
                        # Is there ever a bad call?
                        print("Bad call, folding")
                        fold(player)
                    continue

                case RaiseAction(amount=amount):
                    if amount > game_state.curr_bet and amount <= player.chips:
                        game_state.pot += amount - player.curr_bet
                        player.chips -= amount - player.curr_bet
                        player.curr_bet = amount
                        player.last_action = action
                        game_state.curr_bet = amount
                        # set all other players to unready
                        for p in players:
                            if p.in_hand:
                                p.ready = False
                        player.ready = True
                    else:
                        print("Bad raise, folding")
                        fold(player)
                    continue

                case FoldAction():
                    fold(player)
                    continue
                case _:
                    print("Invalid Action, folding")
                    fold(player)
                    continue
    game_state.reset_turn()


"""
Simple function to check if all players are ready to end round

@param players: list of players

@return bool
"""


def players_not_ready(players):
    for p in players:
        if p.in_hand and not p.ready:
            return True
    return False


"""
Plays a round of poker, resets players turns and rotates position ordering at end of round

@param players: list of players
@param ante: ante chip cost
@param blinds: tuple of small and big blind
"""


def play_poker_round(players, ante=0, blinds=[0, 0], visual=False):
    deck = Deck()
    deck.shuffle()

    game_state = GameState(players=players, deck=deck, ante=ante)

    print("Bots created!")
    game_state.reset_round(ante=ante, blinds=blinds)
    # Pre-flop: Deal 2 cards to each player
    for player in players:
        if player.in_hand:
            player.receive_cards(deck.deal(2))
            if visual:
                print(f"\n{player.name}'s hand:")
                print_cards_as_ascii(player.hand)
            else:
                print(f"{player.name} is dealt: {player.show_hand()}")

    # Placeholder betting round
    print("\n-- Betting Round (Pre-Flop) --\n")
    betting_round(players, game_state)

    # Flop
    deck.burn(1)
    deck.deal_table(3)
    if visual:
        print(f"\nFlop: ")
        print_cards_as_ascii(deck.community_cards)
    else:
        print(f"Flop: {deck.show_table()}")
    print("\n-- Betting Round (Post-Flop) --\n")
    betting_round(players, game_state)

    # Turn
    deck.burn(1)
    deck.deal_table(1)
    if visual:
        print(f"\nTurn: ")
        print_cards_as_ascii(deck.community_cards)
    else:
        print(f"Turn: {deck.show_table()}")
    print("\n-- Betting Round (Post-Turn) --\n")
    betting_round(players, game_state)

    # River
    deck.burn(1)
    deck.deal_table(1)
    if visual:
        print(f"\nRiver: ")
        print_cards_as_ascii(deck.community_cards)
    else:
        print(f"River: {deck.show_table()}")
    print("\n-- Betting Round (Final) --\n")
    betting_round(players, game_state)

    # Showdown
    print("\n-- Showdown --")
    winners, score = compare_players(players, deck.community_cards)

    if len(winners) == 1:
        print(
            f"\n🏆 {winners[0].name} wins with a hand score of {hand_score[score[0]]}, {score[1]}"
        )
        print(f"Pot size of {game_state.pot}")
        winners[0].chips += game_state.pot
    else:
        print(f"\n🤝 It's a tie between: {', '.join(w.name for w in winners)}")
        print(f"Splitting a pot size of {game_state.pot}")
        for w in winners:
            w.chips += game_state.pot // len(winners)

    print(f"Standings:")
    for p in players:
        p.bot.end_game(json.dumps(game_state.to_end_dict()))
        print(f"{p.name}: {p.chips}")
        p.in_hand = True
        p.ready = False
        p.hand = []

    # Rotate starting position of players
    players = [players[-1]] + players[:-1]


"""
Terminates players

@param players: list of players
"""


def terminate(players):
    for player in players:
        player.conn.send("terminate")
        player.bot.join()


# Start Game
players = load_players_from_folder("bots", starting_chips=5000)

antes = [
    1,
    1,
    1,
    2,
    2,
    2,
    5,
    5,
    5,
    5,
    5,
    10,
    10,
    10,
    10,
    10,
    20,
    20,
    20,
    20,
    50,
    50,
    50,
    100,
]
blinds = [
    [1, 2],
    [1, 2],
    [1, 2],
    [2, 4],
    [2, 4],
    [2, 4],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [5, 10],
    [20, 50],
    [20, 50],
    [20, 50],
    [20, 50],
    [50, 100],
    [50, 100],
    [100, 250],
    [100, 250],
]

# antes is a list of antes per round
antes = [5]
# blinds is a list of blinds used per round
blinds = [[10, 20]]

for i in range(len(antes)):
    play_poker_round(players, ante=antes[i], blinds=blinds[i], visual=True)
    if len(players) == 1:
        break

sorted_players = sorted(players, key=attrgetter("chips"), reverse=True)
print("Top 2 move on (if they have enough chips for next antes)")
for p in sorted_players:
    print(f"{p.name} has {p.chips} chips.")


terminate(players)
