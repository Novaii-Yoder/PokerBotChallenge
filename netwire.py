import json
import socket
import struct

"""
Internal wire format for communicating with bots.
"""

def send_json(sock, obj):
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_json(sock, max_bytes=1 << 20):
    hdr = _recvall(sock, 4)
    if not hdr:
        raise ConnectionError("closed")
    n = struct.unpack(">I", hdr)[0]
    if n > max_bytes:
        raise ValueError("msg too large")
    return json.loads(_recvall(sock, n).decode("utf-8"))


def _recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed early")
        buf.extend(chunk)
    return bytes(buf)
