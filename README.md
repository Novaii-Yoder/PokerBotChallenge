# Yoder's Summer(?) Challenge 2025
## Poker Competition

This challenge is to build a poker bot to play in a game of Texas Hold'em. This includes Machine Learning algorithms, as well as statistical and mathematical evaluations of the game. 

The goal is to build or train an algorithm that can play the game not necessarily optimally, but evaluate risk vs. reward. You can build a bot that always make the statistically best choice, but this might lose to a bot that goes all in every hand. The goal is to learn or read the other bots in the game and play the players not only the game.

The ultimate goal of this project is to host a tournament of bots at the end of the year(?) and see who made the best bot. But you are welcome to just do it for fun on your own. For people who want to be in the tournament, try to keep the compute demands pretty small as I will be running all the bots at the same time in container, incase you monsters try to hurt the other bots.

You can provide your own ML models if you would like, again keep in mind potential compute limitations. You are also welcome to train on the fly while the game is running.

Suggestions are welcome, as I am still deciding on how to structure this challenge, and would love to hear from people who are interested in trying.

## Game
These rounds of Texas Hold'em will have an increasing ante and will allow a player to play if they can pay the ante (and blinds), even if that is all they can bet. There is no side pots (currently), and if a player who was all in wins, they will take the pot even if bets beyond their all in were made by other players.

The engine that hosts the games and communicates with the bots is subject to change and is not in the scope of the challenge!

For those who don't know the rules:

- Each player pays an ante, or 'buy in' fee.
- Player 1 in the turn order is known as the 'small blind' and will pay the small blind cost into the pot to play.
- Player 2 is the 'big blind' and must put into the pot the big blind which is usually double the small blind.
- Each player is dealt 2 cards as their hand. 
- Once cards are dealt there is a betting phase, where player after the big blind will start. 
  - They can 'call' the big blind, meaning pay the same amount as big blind. 'raise' to a number bigger than the blind, or 'fold' removing themselves from the round.
  - Once everyone has called the largest raise or folded, the betting round is over.
- The 'flop' is where the dealer pull 3 cards from the deck, followed by another betting round.
- Then the 'turn' is 1 additional card from the deck, followed by a betting round.
- Finally, the 'river' is the 5th card pulled from the deck, which is followed by a final betting round.
- Out of the players still in the round, the one with the best hand is the winner, using standard poker card hands.

~~~    
Royal Flush - Ace, King, Queen, Jack, 10 of same suit
Straight Flush - any straight of same suit
Four of a kind - four of the same rank card
Full House - a three of a kind and a pair
Flush - 5 cards of same suit
Straight - a consecutive order of 5 cards (i.e. 3,4,5,6,7)
Three of a kind - three of the same rank card
Two pair - two seperate pairs
Pair - two cards of same rank
High Card - highest value card in hand
~~~

## Files
### engine.py

Contains the host for the poker game, initializes players and sends data to them for evaluation. Hosts the game, keeps track of the board, players, and game state.

This file is subject to change, improvements to logic and restrictions on players trying to circumvent the rules will be added periodically.

### netwire.py / engine_net.py 

These files are internal functions for communicating with the bots from the engine.

### board.py

This contains the definition for the Card, Board, and GameState objects which are used by the engine and bots to understand the game.
Card and Deck are the only ones the bots really need as the game information is encoded into a json for bots to read. Using the Card obj is by no means required, but you need it if you want to use the same evaluation functions as the engine (you can write your own too). Deck is valuable if you want your bot to keep track of previous hands seen...

### config.json / CONFIG.md

This is the configuration file for engine.py. Information on how to set it up can be found in CONFIG.md.

### manage_bots.py

This is a tool for starting/checking/stopping bots based on the configuration in the config.json file. It can launch
Python scripts/modules, native executables, or arbitrary command strings as specified in `config.json` (see notes below).
Notes about starting bots with `manage_bots.py`:
- `manage_bots.py` supports several config fields to start bots automatically:
  - `cmd`: a raw command string executed via `bash -lc`.
  - `exe` or `bin`: path to a native executable.
  - `path`: path to a Python script (run with the project's Python interpreter).
  - `module`: Python module to run with `python -m`.
- The script will construct and run the command using the host/port/name configured for the bot and will report a clear error if no runnable command is specified.

### bots/

The `bots/` folder contains sample bots for you to view and copy; they are simple examples that show the functions and protocol the engine expects. The engine does not use files from this folder — instead it connects to the host/port entries in `config.json` and only uses bots listed in that file. The engine enforces a remote-only policy: bots must be standalone TCP servers that accept framed-JSON messages (see protocol section below).

## Requirements
Python Version: `Python 3.12.4`

### How to build a bot
A bot can be in any language you want! This is because now the engine is using TCP to communicate with the bots, which means if you can create a server that accepts and return JSON, you can use it for the challenge.

Bot protocol (framed JSON):

Engine -> Bot (act request):
```json
<4-byte BE length> {"op":"act","state":{...}}
```

Bot -> Engine (response to act):
```json
<4-byte BE length> {"move":"raise","amount":150}
```

The engine will wait a short time for a response and eventually drop the connection and auto-fold for the bot. 


## Things to think about
I have added a function that is called at the end of every round, that will show the bots the hands and final actions of players (if players fold, hands are hidden). This is a way for you to check if other bots were bluffing or playing safe. The goal is that you can use this information to learn and predict your opponents moves, adding some dynamics to the game.

One of the easiest tactics to mess with well trained bots is to go all in, all the time. I challenge you to find a good way to counter this strategy, as I am almost certain at least one person will submit a bot like that...
