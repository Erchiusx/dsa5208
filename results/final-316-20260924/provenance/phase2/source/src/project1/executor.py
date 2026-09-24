from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .model import Observation


class Executor(ABC):
    @abstractmethod
    def execute(self, index: int, step: dict[str, Any]) -> Observation:
        """Execute one trajectory step and return a client-visible observation."""
        raise NotImplementedError
