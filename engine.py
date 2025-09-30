import contextlib
import importlib
import importlib.util
import json
import multiprocessing
import os
import random
import time
from operator import attrgetter
import socket

from netwire import recv_json, send_json
from board import *
from engine_net import ask_bot_tcp

"""
Jacob Yoder
9/25/2025

The engine for a poker bot tournament.

Needs:
    ???
"""


"""
Player obj: used for engine side only
"""


class Player:
    def __init__(self, name="bot", host=None, port=None, chips=100):
        self.name = name
        self.hand = []
        self.in_hand = True
        self.chips = chips
        self.last_action = None
        self.curr_bet = 0
        self.ready = False
        self.host = host
        self.port = int(port)

    def receive_cards(self, cards):
        self.hand.extend(cards)
        
    def show_hand(self):
        return [str(card) for card in self.hand]

    def action(self, game_state):
        if self.host and self.port is not None:
            return ask_bot_tcp(self.host, self.port, game_state)
        return FoldAction()


"""
Loads players and rules from config file.
"""


def load_from_config(config_path, default_host="127.0.0.1", base_port=5001):
    """Returns (players, rules, spawned_procs). `players` are socket-based."""
    config_path = os.path.abspath(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    game = config.get("game", {})
    starting_chips = int(game.get("starting_chips", 100))
    num_decks = int(game.get("num_decks", 1))

    bots = config.get("bots", [])
    players, spawned = [], []
    for i, b in enumerate(bots):
        # Process (local/module) bots no longer supported, for language-agnostic-ness
        name = b.get("name", f"bot{i+1}")
        host = b.get("host", default_host)
        port = int(b.get("port", base_port + i))

        players.append(Player(name=name, host=host, port=port, chips=starting_chips))

    rules = {
        "starting_chips": starting_chips,
            "num_decks": num_decks,
            "max_players": int(game.get("max_table_size", len(players))),
            "visual": bool(game.get("visual", False)),
            "delay": float(game.get("delay", 0)),
    }
    return players, rules, spawned


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
        for player in players[2:] + players[:2]:  # Start with non-blinds players
            if player.ready:
                continue
            if player.in_hand:
                # Before getting action, check if last player
                left = [p for p in players if p.in_hand]
                if len(left) == 1:
                    return left[0]

                gs = game_state.to_safe_dict()
                gs["hand"] = [x.to_dict() for x in player.hand]
                gs["player_curr_bet"] = player.curr_bet

                try:
                    action = ask_bot_tcp(player.host, player.port, gs, timeout_s=max_time)
                except Exception as e:
                    # If a bot dies or communication fails, mark them out of the hand
                    print(f"[WARN] bot {player.host}:{player.port} comms error: {e}")
                    # Treat as folded / disconnected for this hand
                    player.last_action = FoldAction()
                    player.in_hand = False
                    player.ready = True
                    print(f"{player.name}: connection error, removed from hand")
                    continue

                if action is None:  # Fun fact `if not action` doesn't work here, because empty enum is False
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

                case CallAction():
                    # verify player can call
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
                    # Treat `amount` as the absolute bet the player wants to have on the table.
                    want = int(amount)
                    need = want - player.curr_bet
                    if need <= 0:
                        # raising to less-or-equal current bet is invalid
                        print("Bad raise (not above current bet), folding")
                        fold(player)
                        continue

                    if need <= player.chips:
                        # normal raise
                        game_state.pot += need
                        player.chips -= need
                        player.curr_bet = want
                        player.last_action = action
                        game_state.curr_bet = max(game_state.curr_bet, want)
                        # set all other players to unready
                        for p in players:
                            if p.in_hand:
                                p.ready = False
                        player.ready = True
                    else:
                        # player cannot cover full raise -> go all-in with remaining chips
                        print("Player raised more than they have... Going all in!")
                        all_in_amt = player.chips
                        game_state.pot += all_in_amt
                        player.curr_bet += all_in_amt
                        player.chips = 0
                        player.last_action = action
                        # update current bet to the highest seen so far
                        game_state.curr_bet = max(game_state.curr_bet, player.curr_bet)
                        # set all other players to unready
                        for p in players:
                            if p.in_hand:
                                p.ready = False
                        player.ready = True
                    continue

                case FoldAction():
                    fold(player)
                    continue
                case _:
                    print("Invalid Action, folding")
                    fold(player)
                    continue

    game_state.reset_turn()
    # If at any point only one player remains in hand, return them as winner
    left = [p for p in players if p.in_hand]
    if len(left) == 1:
        return left[0]
    return None


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
Simple function to notify players of end of round.

@param host: player host
@param port: player port
@param end_state: the dict of game_state
@param timeout_s: timeout in seconds
"""


def notify_end(host, port, end_state, timeout_s=2.0):
    try:
        with contextlib.closing(
            socket.create_connection((host, port), timeout=timeout_s)
        ) as s:
            send_json(s, {"op": "end", "state": end_state})
    except Exception as e:
        # Don't let unreachable bots crash the engine; log and continue.
        print(f"[WARN] failed to notify {host}:{port} -> {e}")


def award_pot_to_player(winners, players, game_state, reason=None, reset_deck=False):
    """Award the pot to one or more winners, notify players, reset transient
    state, and rotate the dealer/button.

    winners may be a single Player or a list of Players. The function will
    correctly split the pot for multiple winners and distribute any remainder
    to the first winner.
    reset_deck indicates if the deck was verified and needs resetting.
    """
    if not winners:  # Protect against empty winners list
        print("Warning: No winners provided to award_pot_to_player")
        # Find someone still in hand to award to, or lowest stack as fallback
        winners = [next((p for p in players if p.in_hand), min(players, key=lambda p: p.chips))]
    # normalize to list
    if isinstance(winners, Player):
        winners = [winners]
    winner_names = [w.name for w in winners]

    if len(winners) == 1:
        print(f"\n-- {winners[0].name} wins ({'early' if reason=='early' else 'showdown'}) --")
        print(f"Awarding pot of {game_state.pot} to {winners[0].name}")
        winners[0].chips += game_state.pot
    else:
        print(f"\n-- Split pot between: {', '.join(winner_names)} --")
        total = game_state.pot
        share = total // len(winners)
        remainder = total - share * len(winners)
        for i, w in enumerate(winners):
            add = share + (remainder if i == 0 else 0)
            w.chips += add
        print(f"Each winner receives {share} chips (remainder {remainder} -> {winner_names[0]})")

    # Reset pot and per-player bet state
    game_state.pot = 0
    game_state.curr_bet = 0
    # notify and cleanup
    for p in players:
        try:
            notify_end(
                p.host,
                p.port,
                game_state.to_end_dict(winner_names, p.name, reset_deck=reset_deck),
                timeout_s=2.0,
            )
        except Exception:
            print(f"[WARN] failed to notify {p.name} of end")
        print(f"{p.name}: {p.chips}")
        p.in_hand = True
        p.ready = False
        p.hand = []
        p.curr_bet = 0
    # rotate seating (move dealer/button)
    temp = players.pop(0)
    players.append(temp)


"""
Plays a round of poker, resets players turns and rotates position ordering at end of round

@param players: list of players
@param blinds: tuple of small and big blind
"""


def play_poker_round(deck, players, blinds=[0, 0], visual=False, delay=0):
    time.sleep(delay)

    if len(players) < 2:
        print(f"Not enough players to play")
        return

    # Check if we have enough players who can afford blinds
    can_play = sum(1 for p in players if p.chips >= blinds[1])
    if can_play < 2:
        print(f"Not enough players can afford big blind ({blinds[1]}), skipping round")
        return

    game_state = GameState(players=players, deck=deck)

    game_state.reset_round(blinds=blinds)

    # Pre-flop: Deal 2 cards to each player
    for player in players:
        player.hand = [] # make sure to reset hand
        if player.in_hand:
            player.receive_cards(deck.deal(2))
            if visual:
                print(f"\n{player.name}'s hand:")
                print_cards_as_ascii(player.hand)
            else:
                print(f"{player.name} is dealt: {player.show_hand()}")

    # Placeholder betting round
    print("\n-- Betting Round (Pre-Flop) --\n")
    early_winner = betting_round(players, game_state)
    if early_winner:
        award_pot_to_player(early_winner, players, game_state)
        return
    time.sleep(delay)

    # Flop
    deck.burn(1)
    deck.deal_table(3)
    if visual:
        print(f"\nFlop: ")
        print_cards_as_ascii(deck.community_cards)
    else:
        print(f"Flop: {deck.show_table()}")
    print("\n-- Betting Round (Post-Flop) --\n")
    early_winner = betting_round(players, game_state)
    if early_winner:
        award_pot_to_player(early_winner, players, game_state)
        return
    time.sleep(delay)

    # Turn
    deck.burn(1)
    deck.deal_table(1)
    if visual:
        print(f"\nTurn: ")
        print_cards_as_ascii(deck.community_cards)
    else:
        print(f"Turn: {deck.show_table()}")
    print("\n-- Betting Round (Post-Turn) --\n")
    early_winner = betting_round(players, game_state)
    if early_winner:
        award_pot_to_player(early_winner, players, game_state)
        return
    time.sleep(delay)

    # River
    deck.burn(1)
    deck.deal_table(1)
    if visual:
        print(f"\nRiver: ")
        print_cards_as_ascii(deck.community_cards)
    else:
        print(f"River: {deck.show_table()}")
    print("\n-- Betting Round (Final) --\n")
    early_winner = betting_round(players, game_state)
    if early_winner:
        award_pot_to_player(early_winner, players, game_state, reason="early")
        return

    # Only do showdown if we have multiple players still in
    left = [p for p in players if p.in_hand]
    if len(left) < 2:
        if left:
            award_pot_to_player(left[0], players, game_state, reason="last standing")
        else:
            # If no players remain in the hand, award pot to fallback winner
            print("Warning: No players left in hand at showdown -- awarding pot to fallback winner")
            # (first in-hand or lowest stack).
            award_pot_to_player(None, players, game_state, reason="no_players_left")
        return

    # Showdown
    print("\n-- Showdown --")
    winners, score = compare_players(players, deck.community_cards)

    # Check if deck needs resetting
    need_reset = deck.verify(len(players))
    award_pot_to_player(winners, players, game_state, reason="showdown", reset_deck=need_reset)


"""
Terminates players

@param players: list of players
"""


def terminate(players):
    for player in players:
        with contextlib.closing(
            socket.create_connection((player.host, player.port), timeout=1)
        ) as s:
            send_json(s, {"op": "terminate"})
            pass


def preflight_check(players, timeout_s=1.0):
    bad = []
    for p in players:
        try:
            with contextlib.closing(
                socket.create_connection((p.host, p.port), timeout=timeout_s)
            ):
                pass
        except OSError as e:
            bad.append((p.name, p.host, p.port, str(e)))
    if bad:
        lines = "\n".join(f"- {n} @ {h}:{pt} -> {err}" for n, h, pt, err in bad)
        raise RuntimeError("Unreachable bots:\n" + lines)


def wait_for_bots(players, timeout_s=5.0, interval=0.25):
    """Retry until all bots accept TCP or timeout."""
    deadline = time.time() + timeout_s
    remaining = {(p.host, p.port, p.name) for p in players}
    last_err = {}
    while remaining and time.time() < deadline:
        ready_now = []
        for host, port, name in list(remaining):
            try:
                with contextlib.closing(
                    socket.create_connection((host, port), timeout=interval)
                ):
                    ready_now.append((host, port, name))
            except OSError as e:
                last_err[(host, port, name)] = str(e)
        for triple in ready_now:
            remaining.discard(triple)
        if remaining:
            time.sleep(interval)
    if remaining:
        lines = "\n".join(
            f"- {n} @ {h}:{pt} -> {last_err.get((h,pt,n),'no response')}"
            for h, pt, n in sorted(remaining)
        )
        raise RuntimeError("Unreachable bots (after wait):\n" + lines)


#####################################################################################
# Tournament definitions
#####################################################################################
def chunked(iterable, size):
    """Yield successive chunks of size `size` from iterable."""
    it = list(iterable)
    for i in range(0, len(it), size):
        yield it[i : i + size]

def print_scoreboard(players, title="Standings"):
    print("\n" + "=" * 40)
    print(f"{title}")
    print("=" * 40)
    sorted_p = sorted(players, key=attrgetter("chips"), reverse=True)
    for i, p in enumerate(sorted_p, start=1):
        print(f"{i:2d}. {p.name:20s} {p.chips:8d} chips")
    print("=" * 40 + "\n")

class Tournament:
        """Simple bracket-style tournament.

        Config (in config.json under key "tournament") accepts:
          - advance_per_table: how many players advance from each table (default 2)
          - max_table_size: override rules.max_players per table
          - rounds_per_match: how many poker rounds to play per table (default 1)
          - visual: pass through to play_poker_round for ascii output
        """

        def __init__(self, players, rules, config=None):
            self.players = list(players)
            self.rules = rules
            config = config or {}
            self.advance_per_table = int(config.get("advance_per_table", 2))
            self.max_table_size = int(rules.get("max_players", 6))
            self.rounds_per_match = int(config.get("hands_per_match", 1))
            self.visual = bool(rules.get("visual", True))
            self.delay = float(rules.get("delay", 0))
            self.blind_step_per_round = int(config.get("blind_step_per_round", 0))
            self.blind_step_per_tier = int(config.get("blind_step_per_tier", 1))
            self.blinds_schedule = config.get("blinds_schedule")

        def run(self):
            # initial check and reset chips
            num_decks = self.rules.get("num_decks", 1)

            # inform bots of deck size at start
            for p in self.players:
                p.chips = self.rules.get("starting_chips", p.chips)
                try:
                    notify_end(
                        p.host,
                        p.port,
                        {"is_end_state": True, "num_decks": num_decks, "reset_deck": True},
                        timeout_s=2.0,
                    )
                except Exception as e:
                    print(f"[WARN] failed to send initial deck info to {p.name}: {e}")

            current = list(self.players)
            tier = 1
            # Tournament loop: group players each tier by chip stacks so top
            # stacks play each other. Advance blind level as tiers progress.
            blind_levels = self.blinds_schedule or self.rules.get("blind_levels", [])
            blind_idx = 0
            while len(current) > self.advance_per_table:
                # Remove players who have run out of chips so we don't repeatedly
                busted = [p for p in current if p.chips <= 0]
                if busted:
                    for p in busted:
                        print(f"Removing busted player from tournament: {p.name}")
                    current = [p for p in current if p.chips > 0]

                print(f"\n-- Tier {tier}: {len(current)} players -> advance {self.advance_per_table} per table --")
                advancers = []

                # Randomize seating at each tier (like real tournaments)
                random.shuffle(current)

                # chunk into tables (random seating)
                tables = list(chunked(current, self.max_table_size))
                for t_idx, table_players in enumerate(tables, start=1):
                    print(f"\nPlaying table {t_idx} with {len(table_players)} players")

                    # choose blind level for this table based on global blind index
                    if blind_levels:
                        lvl = blind_levels[min(blind_idx, len(blind_levels) - 1)]
                        sb = lvl.get("small", 1)
                        bb = lvl.get("big", 2)
                    else:
                        sb = 1
                        bb = 2

                    # Play configured number of rounds (hands) and aggregate chips
                    for r in range(self.rounds_per_match):
                        # Filter out any busted players at the table before each hand
                        table_players = [p for p in table_players if p.chips > 0]
                        if len(table_players) < 2:
                            print(f"Not enough active players at table {t_idx} to continue rounds, ending table early")
                            break

                        # Use current blind level for this hand
                        deck = Deck(self.rules.get("num_decks", 1))
                        deck.shuffle()
                        play_poker_round(deck, table_players, blinds=[sb, bb], visual=self.visual, delay=self.delay)
                        # advance blind index per-round if configured
                        blind_idx += self.blind_step_per_round
                        # clamp to last schedule index
                        if blind_levels:
                            blind_idx = min(blind_idx, len(blind_levels) - 1)

                    # determine advancers from this table (top stacks at the table advance)
                    sorted_table = sorted(table_players, key=attrgetter("chips"), reverse=True)
                    take = min(self.advance_per_table, len(sorted_table))
                    selected = sorted_table[:take]
                    print("Advancing:", ", ".join(p.name for p in selected))
                    # reset transient table state
                    for p in table_players:
                        p.in_hand = True
                        p.ready = False
                        p.hand = []
                    advancers.extend(selected)

                # prepare for next tier
                # deduplicate advancers (same bot shouldn't advance twice)
                seen = set()
                next_round = []
                for p in advancers:
                    if p.name not in seen:
                        seen.add(p.name)
                        next_round.append(p)

                # increase blind index for next tier (blinds go up over time)
                blind_idx += self.blind_step_per_tier
                if blind_levels:
                    blind_idx = min(blind_idx, len(blind_levels) - 1)

                current = next_round
                tier += 1

            print("\nTournament finished. Finalists:")
            print_scoreboard(current, title="Finalists")
            # merge final ranking with all players for a full board
            final_board = sorted(self.players, key=attrgetter("chips"), reverse=True)
            print_scoreboard(final_board, title="Final Standings")

            return current

if __name__ == "__main__":
    # Start Tournament
    players, rules, _spawned = load_from_config("config.json")

    config = {}
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config_all = json.load(f)
            config = config_all.get("tournament", {})
    except Exception:
        config = {}

    # ensure bots are reachable before starting
    wait_for_bots(players, timeout_s=5.0)
    preflight_check(players)

    tour = Tournament(players, rules, config=config)
    winners = tour.run()

    # lets not terminate bots for now
    #terminate(players)

