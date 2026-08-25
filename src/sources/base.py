
from __future__ import annotations
from abc import ABC, abstractmethod
from ..models import Job

class JobSource(ABC):
    name = "base"
    @abstractmethod
    def search(self, query: str, location: str, limit: int = 30) -> list[Job]:
        raise NotImplementedError
