import contextlib
import json
import socket

from board import CallAction, CheckAction, FoldAction, RaiseAction
from netwire import recv_json, send_json

"""
Internal for communicating with bots.
"""


def ask_bot_tcp(host, port, state, timeout_s=2.0):
    try:
        with contextlib.closing(
            socket.create_connection((host, port), timeout=timeout_s)
        ) as s:
            s.settimeout(timeout_s)
            send_json(s, {"op": "act", "state": state})
            resp = recv_json(s)
            #print(f"[wire] {host}:{port} -> {resp!r}")
            mv = resp.get("move")
            if isinstance(mv, str):
                mv = mv.strip().lower()
            if mv == "raise":

                def first_present(d, keys):
                    for k in keys:
                        if k in d and d[k] is not None:
                            return d[k]
                    return None

                amt = first_present(resp, ("amount", "raise_to", "value", "amt"))

                return RaiseAction(int(amt))
            if mv == "call":
                return CallAction()
            return FoldAction()
    except (OSError, ConnectionError, ValueError, json.JSONDecodeError) as e:
        print(f"[WARN] bot {host}:{port} comms error: {e}")
        return FoldAction()
