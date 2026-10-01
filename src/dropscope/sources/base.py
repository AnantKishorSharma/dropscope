"""Abstract drop-event source.

Every producer (synthetic scenario, real MOD feed, recorded capture) yields the
same normalized `DropEvent` objects, so the correlation/aggregation layers are
completely decoupled from where drops come from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..models import DropEvent


class DropEventSource(ABC):
    name: str = "base"

    @abstractmethod
    def events(self) -> Iterable[DropEvent]:
        """Yield `DropEvent`s (bounded for replay, unbounded for live feeds)."""
        raise NotImplementedError
