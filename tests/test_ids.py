"""ID 결정성 테스트.

구현 1단계에서 가장 먼저 통과시켜야 하는 테스트다.
여기가 깨지면 캐시가 조용히 잘못된 데이터를 돌려준다.
"""

import pytest

pytestmark = pytest.mark.skip(reason="ms_dataflow.ids 구현 전")


def test_lineage_key_is_deterministic():
    """같은 입력이면 항상 같은 lineage_key."""


def test_lineage_key_ignores_slot_order():
    """입력 슬롯을 이름으로 해시하므로 나열 순서는 무관하다."""


def test_lineage_key_differs_by_slot_name():
    """같은 artifact가 다른 슬롯에 쓰이면 다른 키."""


def test_planned_id_matches_resolver_issued_id():
    """Planner의 planned_id와 Resolver 발급 값이 같아야 한다."""


def test_version_ignores_comments_and_whitespace():
    """주석·공백·docstring만 다른 함수는 같은 version."""


def test_version_changes_with_logic():
    """로직이 다르면 다른 version."""
