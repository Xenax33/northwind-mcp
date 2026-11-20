"""A small in-memory event bus feeding the page's live log (Server-Sent Events).

Every event is kept in a bounded history, so a page opened later still sees the
connection handshake and the tool listing that happened at startup.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import deque
from typing import Any

HISTORY_SIZE = 1000


class EventBus:
    def __init__(self) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_SIZE)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._ids = itertools.count(1)

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        event = {"id": next(self._ids), "ts": time.time(), "kind": kind, **data}
        self._history.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for event in self._history:
            queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)
