"""
A script to manage (start/stop/status) poker bot processes from a JSON config.

Author: ChatGPT
Run at your own risk.
"""

import argparse
import contextlib
import json
import os
import pathlib
import shlex
import shutil
import socket
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.append(str(REPO_ROOT))  # so we can import netwire from repo root

try:
    from netwire import recv_json, send_json
except Exception:
    # minimal fallback terminate sender if import fails
    import json as _json
    import struct

    def _send_all(sock, b):
        view = memoryview(b)
        while view:
            n = sock.send(view)
            view = view[n:]

    def send_json(sock, obj):
        b = _json.dumps(obj, separators=(",", ":")).encode("utf-8")
        _send_all(sock, struct.pack("!I", len(b)))
        _send_all(sock, b)


def shell_join(args):  # safe shell string
    return " ".join(shlex.quote(str(a)) for a in args)


def resolve_path(base_cfg, maybe_rel):
    if not maybe_rel:
        return None
    p = pathlib.Path(maybe_rel)
    if p.is_absolute():
        return str(p)
    return str((pathlib.Path(base_cfg).parent / p).resolve())


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    bots = cfg.get("bots", [])
    return bots


def find_terminal():
    # ordered preference
    emus = [
        (
            "gnome-terminal",
            lambda cmd, title: [
                "gnome-terminal",
                "--title",
                title,
                "--",
                "bash",
                "-lc",
                f"{cmd}; exec bash",
            ],
        ),
        (
            "konsole",
            lambda cmd, title: [
                "konsole",
                "-p",
                f"tabtitle={title}",
                "-e",
                "bash",
                "-lc",
                f"{cmd}; exec bash",
            ],
        ),
        (
            "kitty",
            lambda cmd, title: [
                "kitty",
                "--title",
                title,
                "bash",
                "-lc",
                f"{cmd}; exec bash",
            ],
        ),
        (
            "wezterm",
            lambda cmd, title: ["wezterm", "start", "bash", "-lc", f"{cmd}; exec bash"],
        ),
        (
            "alacritty",
            lambda cmd, title: ["alacritty", "-t", title, "-e", "bash", "-lc", cmd],
        ),
        (
            "xterm",
            lambda cmd, title: [
                "xterm",
                "-T",
                title,
                "-hold",
                "-e",
                "bash",
                "-lc",
                cmd,
            ],
        ),
    ]
    for name, builder in emus:
        if shutil.which(name):
            return name, builder
    return None, None


def open_in_tmux(cmd, title, session="pokerbots"):
    if not shutil.which("tmux"):
        return False
    # create or add window
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode != 0:
            subprocess.check_call(
                ["tmux", "new-session", "-d", "-s", session, "-n", title, cmd]
            )
        else:
            subprocess.check_call(
                ["tmux", "new-window", "-t", session, "-n", title, cmd]
            )
        return True
    except Exception:
        return False


def open_in_terminal(cmd, title):
    name, builder = find_terminal()
    if builder:
        try:
            subprocess.Popen(builder(cmd, title))
            return f"spawned in {name}"
        except Exception:
            pass
    if open_in_tmux(cmd, title):
        return "spawned in tmux (session: pokerbots)"
    # last resort: background process (no terminal)
    subprocess.Popen(
        ["bash", "-lc", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )
    return "spawned in background (no terminal found)"


def build_bot_cmd(bot, cfg_path):
    """
    Build the command used to start a bot process.

    Supported config fields (checked in this order):
    - "cmd": raw command string to run (executed via bash -lc)
    - "exe" or "bin": path to a native executable (must be executable)
    - "path": path to a python script
    - "module": python module to run with -m
    If none provided, falls back to repo's `bots/simple_bot.py`.
    """
    py = sys.executable or "python3"
    name = bot.get("name", "Bot")
    host = bot.get("host", "127.0.0.1")
    port = int(bot.get("port", 5001))

    # 1) raw command string
    cmd = bot.get("cmd")
    if cmd:
        # run under bash -lc so the user can provide complex commands
        return f"bash -lc {shlex.quote(cmd)}"

    # 2) native executable (exe/bin)
    exe = bot.get("exe") or bot.get("bin")
    if exe:
        exe_path = resolve_path(cfg_path, exe)
        if exe_path and os.path.isfile(exe_path) and os.access(exe_path, os.X_OK):
            return shell_join([exe_path, "--name", name, "--host", host, "--port", port])

    # 3) python script path
    path = resolve_path(cfg_path, bot.get("path"))
    if path and os.path.isfile(path):
        return shell_join([py, path, "--name", name, "--host", host, "--port", port])

    # 4) python module
    module = bot.get("module")
    if module:
        return shell_join([py, "-m", module, "--name", name, "--host", host, "--port", port])

    # If we reach here, we couldn't determine a runnable command
    raise ValueError(
        f"No runnable command found for bot '{name}'. Provide one of 'cmd', 'exe'/'bin', 'path', or 'module' in the config."
    )


def ping(host, port, timeout=0.5):
    try:
        with contextlib.closing(
            socket.create_connection((host, int(port)), timeout=timeout)
        ):
            return True
    except OSError:
        return False


def terminate(host, port, timeout=1.0):
    try:
        with contextlib.closing(
            socket.create_connection((host, int(port)), timeout=timeout)
        ) as s:
            send_json(s, {"op": "terminate"})
        return True
    except OSError:
        return False


def cmd_start(args):
    bots = load_config(args.config)
    # Optional filter
    names = set(args.name) if args.name else None
    started = []
    for b in bots:
        n = b.get("name", "Bot")
        if names and n not in names:
            continue
        host, port = b.get("host", "127.0.0.1"), int(b.get("port", 0) or 0)
        if port <= 0:
            print(f"skip {n}: missing/invalid port")
            continue
        try:
            cmd = build_bot_cmd(b, args.config)
        except ValueError as e:
            print(f"skip {n}: {e}")
            continue
        where = open_in_terminal(cmd, f"bot-{n}")
        started.append((n, host, port, where))
    if not started:
        print("No bots started (check names/config).")
        return
    print("Started:")
    for n, h, p, where in started:
        print(f" - {n} @ {h}:{p} -> {where}")


def cmd_status(args):
    bots = load_config(args.config)
    print("Status:")
    for b in bots:
        n = b.get("name", "Bot")
        h = b.get("host", "127.0.0.1")
        p = int(b.get("port", 0) or 0)
        if p <= 0:
            print(f" - {n}: invalid port")
            continue
        up = ping(h, p)
        print(f" - {n} @ {h}:{p}: {'UP' if up else 'DOWN'}")


def cmd_stop(args):
    bots = load_config(args.config)
    names = set(args.name) if args.name else None
    any_hit = False
    for b in bots:
        n = b.get("name", "Bot")
        if names and n not in names:
            continue
        h, p = b.get("host", "127.0.0.1"), int(b.get("port", 0) or 0)
        ok = terminate(h, p)
        print(f" - stop {n} @ {h}:{p}: {'OK' if ok else 'no response'}")
        any_hit = True
    if not any_hit:
        print("No matching bots to stop (check --name).")


def cmd_stop_all(args):
    bots = load_config(args.config)
    for b in bots:
        n = b.get("name", "Bot")
        h, p = b.get("host", "127.0.0.1"), int(b.get("port", 0) or 0)
        ok = terminate(h, p)
        print(f" - stop {n} @ {h}:{p}: {'OK' if ok else 'no response'}")


def main():
    ap = argparse.ArgumentParser(description="Launch/stop poker bots from config.")
    ap.add_argument("-c", "--config", default=str(REPO_ROOT / "config.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("start", help="Start bots (one terminal per bot if possible)")
    sp.add_argument(
        "--name", action="append", help="Only start these bot names (repeatable)"
    )
    sp.set_defaults(func=cmd_start)

    ss = sub.add_parser("status", help="Ping bots")
    ss.set_defaults(func=cmd_status)

    st = sub.add_parser("stop", help="Terminate one or more bots by name")
    st.add_argument(
        "--name", action="append", required=True, help="Bot name (repeatable)"
    )
    st.set_defaults(func=cmd_stop)

    sa = sub.add_parser("stop-all", help="Terminate all bots from config")
    sa.set_defaults(func=cmd_stop_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
