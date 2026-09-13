"""``PGEObjectWithTriggers`` - anything in a level that reacts to events.

Recovered from ``-[PGEObjectWithTriggers triggerWithType:]``:

* the object's trigger list is scanned for entries whose ``triggerType`` matches
  the fired event, compared **case-insensitively**;
* a trigger carrying ``count`` may fire that many times and no more;
* a trigger carrying ``afterCount`` is skipped, decrementing, until the count
  reaches 1, and fires from then on;
* the message's parameters get ``senderName`` and ``position`` added;
* with ``afterDelay`` it is scheduled, otherwise it is enqueued for the next
  idle pass (never delivered inline).

Ordering within one object is the order the statements appear in the level data.
"""

from __future__ import annotations

from typing import Any

from ..assets.tiled import Trigger
from .messages import MessageBus, Params


class TriggerHost:
    """Mixin for level objects that own triggers."""

    def __init__(self, bus: MessageBus, name: str = '',
                 position: tuple[float, float] = (0.0, 0.0)) -> None:
        self.bus = bus
        self.name = name
        self.position = position
        self.triggers: list[Trigger] = []
        #: Live per-trigger state, parallel to ``triggers``.
        self._remaining: list[int | None] = []
        self._until: list[int | None] = []

    # ------------------------------------------------------------------
    def add_trigger(self, trigger: Trigger) -> None:
        self.triggers.append(trigger)
        self._remaining.append(trigger.count)
        self._until.append(trigger.after_count)

    def add_triggers(self, triggers) -> None:
        for t in triggers:
            self.add_trigger(t)

    def reset_triggers(self) -> None:
        """Restore firing counts, as a fresh level load would."""
        self._remaining = [t.count for t in self.triggers]
        self._until = [t.after_count for t in self.triggers]

    # ------------------------------------------------------------------
    def trigger(self, trigger_type: str) -> int:
        """Fire every matching trigger. Returns how many actually fired."""
        want = trigger_type.upper()
        fired = 0
        for i, t in enumerate(self.triggers):
            if t.trigger_type.upper() != want:
                continue

            remaining = self._remaining[i]
            if remaining is not None:
                if remaining <= 0:
                    continue
                self._remaining[i] = remaining - 1

            until = self._until[i]
            if until is not None and until > 1:
                self._until[i] = until - 1
                continue

            params: Params = dict(t.parameters)
            params['senderName'] = self.name
            params['position'] = self.position

            if t.after_delay > 0:
                self.bus.post_after(t.after_delay, t.notification_name, params,
                                    token=(id(self), 'trigger', i))
            else:
                self.bus.enqueue(t.notification_name, params)
            fired += 1
        return fired

    # ------------------------------------------------------------------
    def cancel_pending_triggers(self) -> int:
        """Drop this object's scheduled triggers (used by dealloc/shutdown)."""
        n = 0
        for i in range(len(self.triggers)):
            n += self.bus.cancel((id(self), 'trigger', i))
        return n

    def __repr__(self) -> str:
        return f'<{type(self).__name__} {self.name!r} @{self.position}>'


def addressed_to(params: Params, name: str, key: str = 'name') -> bool:
    """Does a broadcast message address the object called ``name``?

    Every agent applies this test itself, which is exactly why a trigger naming
    an agent that does not exist quietly does nothing.
    """
    target = params.get(key)
    return bool(target) and target == name
