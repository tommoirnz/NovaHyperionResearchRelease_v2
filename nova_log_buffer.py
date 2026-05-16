"""
nova_log_buffer.py — Shared circular buffer for Nova's runtime log.

Nova's self.log() writes here. The read_log tool reads from here.
This gives Nova visibility into her own runtime behaviour.
"""

from collections import deque
from datetime import datetime

# ── Circular buffer — keeps last 500 log lines ────────────────────────────────
_buffer: deque = deque(maxlen=500)


def append(line: str) -> None:
    """Append a timestamped line to the buffer. Called by Nova's log() method."""
    ts = datetime.now().strftime("%H:%M:%S")
    _buffer.append(f"[{ts}] {line}")


def get_recent(n: int = 100) -> list:
    """Return the last n lines."""
    return list(_buffer)[-n:]


def get_all() -> list:
    """Return all buffered lines."""
    return list(_buffer)


def clear() -> None:
    """Clear the buffer."""
    _buffer.clear()


def search(keyword: str, n: int = 200) -> list:
    """Return lines from the last n entries that contain keyword (case-insensitive)."""
    keyword = keyword.lower()
    return [line for line in list(_buffer)[-n:] if keyword in line.lower()]
