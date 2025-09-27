Configuration (config.json)

Overview

1) game
- num_decks (int): number of decks to use. Larger values reduce card-counting variance.
- starting_chips (int): starting chip stack for each player at the beginning of the tournament.
- max_table_size (int): default maximum players per table.
- visual (bool): default visual setting for the engine (can be overridden per-tournament).
- delay (float): default delay between visual stages in seconds.

2) bots (array)
Each entry defines a bot. The engine only supports TCP bot servers.
- name (string): human readable name used in logs.
- host (string): host to connect to for the remote bot. Default: 127.0.0.1
- port (int): TCP port for the remote bot server.

Bots must implement the framed-JSON protocol used by the engine: each message is sent as a 4-byte big-endian length followed by a JSON payload. The bot should accept "act" requests and respond with valid actions, accept "end" notifications, and handle "terminate" when the engine shuts down.

3) tournament
- advance_per_table (int): how many players advance from each table to the next tier.
- hands_per_match (int): how many hands to play per table per match. Use this to play multiple hands before selecting advancers.
- blind_step_per_round (int): how many steps to advance in the blind schedule after each hand. Default 0.
- blind_step_per_tier (int): additional steps to advance in the blind schedule after each tier. Default 1.
- blinds_schedule (array): Each entry is { small: (int), big: (int) }.
