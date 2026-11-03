"""In-process event bus: the core publishes what happens, the API streams it to the GUI over WebSocket.

Publishers are worker threads; subscribers must not block (the API hands events to its event loop).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

log = logging.getLogger(__name__)
Event = dict
Subscriber = Callable[[Event], None]

_lock = threading.Lock()
_subscribers: list[Subscriber] = []


def subscribe(fn: Subscriber) -> Callable[[], None]:
    with _lock:
        _subscribers.append(fn)

    def unsubscribe() -> None:
        with _lock:
            if fn in _subscribers:
                _subscribers.remove(fn)
    return unsubscribe


def publish(event_type: str, **data) -> None:
    event = {"type": event_type, "ts": datetime.now(UTC).isoformat(timespec="milliseconds"), **data}
    with _lock:
        targets = list(_subscribers)
    for fn in targets:
        try:
            fn(event)
        except Exception:  # one broken listener (e.g. a closed GUI socket) must not stop a running job
            log.exception("event subscriber failed on %s", event_type)
