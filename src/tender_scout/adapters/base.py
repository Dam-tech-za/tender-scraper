"""Source adapter contract. Adapters fetch and parse only: no scoring, no storage, no email."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from tender_scout.models import Tender


class SourceAdapter(ABC):
    source_name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @property
    def is_fallback(self) -> bool:
        return bool(self.config.get("fallback", False))

    @abstractmethod
    def fetch(self) -> Iterable[Tender]:
        """Yield open tenders from this source."""
