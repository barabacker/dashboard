"""CountingSink — a LotSink that counts instead of storing.

The back office has no table for collected lots yet (see the decision recorded in CLAUDE.md), so
a run reports *what it found* and keeps nothing. This sink is what makes that a real crawl
rather than a truncated one: ``get_fingerprints`` answers "nothing known", which is what tells
the fogsoft engine every listing row is worth diving into.

It also keeps a handful of lot ids so a finished Job shows something recognisable next to its
counts.
"""

from __future__ import annotations

from collections.abc import Sequence

from collectors.engine.core.lot import Lot
from collectors.engine.core.storage.contracts import ChangeStatus


class CountingSink:
    """Counts every emitted lot; remembers the first ``sample_size`` lot ids."""

    def __init__(self, sample_size: int = 5) -> None:
        self.sample_size = sample_size
        self.count = 0
        self.sample: list[str] = []

    async def get_fingerprints(self, source: str, lot_ids: Sequence[str]) -> dict[str, str]:
        """Nothing is stored, so nothing is known — every lot reads as new."""
        return {}

    async def save(self, item: Lot) -> ChangeStatus:
        self.count += 1
        if len(self.sample) < self.sample_size:
            self.sample.append(item.lot_id)
        return ChangeStatus.NEW
