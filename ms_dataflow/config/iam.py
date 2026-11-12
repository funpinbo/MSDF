"""IAM 규칙. (M3에서 구현)"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ms_dataflow.models import Dag, Delivery, Order


class Iam:
    def check_order(self, order: Order, dag: Dag, delivery: Delivery) -> list[str]:
        return []

    def missing_context_keys(self, keys: tuple[str, ...] | None) -> list[str]:
        return []


def load_iam(path: Path, registry: Any = None) -> Iam | None:
    return None
