from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ..models import Job


class JobSource(ABC):
    """Base class for job discovery sources.

    category is used only for transparent discovery reporting:
      - broad: discovers jobs across many employers
      - watchlist: monitors configured ATS/company boards
      - inbox: ingests alert files
      - manual: user-supplied URLs
    """

    name = "base"
    category = "broad"
    automatic = True

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "automatic": self.automatic,
            "configured": True,
            "operational": True,
            "reason": "ready",
        }

    @abstractmethod
    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        raise NotImplementedError

    def search_many(self, queries: list[str], locations: list[str], limit: int = 30) -> list[Job]:
        out: list[Job] = []
        locs = locations or [""]
        for query in queries or [""]:
            for location in locs:
                out.extend(self.search(query, location, limit))
        return out
