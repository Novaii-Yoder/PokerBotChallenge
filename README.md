# Yoder's Summer Challenge 2025
## Poker Competition

This challenge is to build a poker bot to play in a game of Texas Hold'em. I hope to have a few people build bots by the end of the summer so that I can host a little tournament and see who's bot is best.

The goal is to build or train an algorithm that can play the game not optimally, but evaluate risk vs. reward. You can build a bot that always make the statistcally best choice, but this might lose to a bot that goes all in every hand. The goal is to learn or read the other bots in the game and play the players not only the game.

Suggestions are welcome, as I am still deciding on how to structure this challenge, and would love to hear from people who are interested in trying.

## Game
These rounds of Texas Hold'em will have an increasing ante and will allow a player to play if they can pay the ante (and blinds), even if that is all they can bet. There is no side pots, and if a player who was all in wins, they will take the pot even if bets beyond their all in were made by other players.

The engine that hosts the games and communicates with the bots is subject to change and is not in the scope of the challenge!


## Files
### engine.py

Contains the host for the poker game, initializes players and sends data to them for evaluation. Hosts the game, keeps track of the board, players, and game state.

This file is subject to change, improvements to logic and restrictions on players trying to circumvent the rules will be added periodically.

### board.py

This contains the definition for the Card, Board, and GameState objects which are used by the engine and bots to understand the game.
Card is the only one the bots really need as the game information is encoded into a json for bots to read. Using the Card obj is by no means required, but you need it if you want to use the same evaluation functions as the engine (you can write your own too).

### bots/

The bots folder contains sample bots for you to view and copy if you so choose, they are very simple, mostly there to show you the functions required to work with the engine. You can put as many bots as you want into the folder, but only the first 5 alphabetically will be used in the current implementation of engine.py. You can edit this for testing if you'd like but there will likely be no more than 5 players at the table for the competition.

## Things to think about
I have added a function that is called at the end of every round, that will show the bots the hands and final actions of players (if players fold, hands are hidden). This is a way for you to check if other bots were bluffing or playing safe. The goal is that you can use this information to learn and predict your opponents moves, adding some dynamics to the game.
