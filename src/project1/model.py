from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Observation:
    index: int
    op: str
    status: str = "ok"
    client: str | None = None
    node: str | None = None
    key: str | None = None
    version: int | None = None
    write_id: str | None = None
    seq: int | None = None
    depends_on: dict[str, Any] | None = None
    order: list[str] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    property_name: str
    status: str  # PASS | VIOLATION | INCONCLUSIVE
    reason: str
    witness: list[int] = field(default_factory=list)
