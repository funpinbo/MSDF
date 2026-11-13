"""examples/chatbot이 LLM 없이 예시 데이터로 끝까지 동작하는지 확인한다."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ms_dataflow.decorators import _CONTEXT, resolve_function
from ms_dataflow.errors import PermissionDenied
from ms_dataflow.execute.local import LocalRunner

EXAMPLE = Path(__file__).parent.parent / "examples" / "chatbot"


@pytest.fixture
def chatbot_dir(tmp_path):
    root = tmp_path / "chatbot"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".msdf", "__pycache__"))
    yield root
    _CONTEXT.clear()


def test_chatbot_answers_from_sample_docs(chatbot_dir):
    with LocalRunner(chatbot_dir) as r:
        chatbot = resolve_function(str(chatbot_dir / "chatbot.py"), "chatbot")
        answers = chatbot.__globals__["ANSWERS"]
        chatbot("환불은 언제 되나요")
        r.run_until_idle()
        assert answers[-1].startswith("환불 정책:")
        assert [s.node for s in r.last.plan.steps] == ["fetch", "embed", "refine"]

        chatbot("환불은 언제 되나요")
        r.run_until_idle()
        assert r.last.plan.steps == [] and r.last.plan.cached == ["fetch", "embed", "refine"]
        assert answers[-1] == answers[-2]

        chatbot("우주선 발사 일정")
        r.run_until_idle()
        assert answers[-1] == "관련 문서를 찾지 못했습니다."

    # 검색 결과는 resolvers.yaml에 따라 SQLite에 저장된다
    assert (chatbot_dir / ".msdf" / "search.db").exists()


def test_chatbot_answers_go_to_the_right_session(chatbot_dir):
    with LocalRunner(chatbot_dir) as r:
        chatbot = resolve_function(str(chatbot_dir / "chatbot.py"), "chatbot")
        by_session = chatbot.__globals__["BY_SESSION"]
        chatbot("환불은 언제 되나요", session_id="alice")
        chatbot("배송 조회는 어디서 하나요", session_id="bob")
        chatbot("환불은 언제 되나요", session_id="bob")
        r.run_until_idle()
    assert by_session["alice"] == [by_session["bob"][1]]
    assert by_session["alice"][0].startswith("환불 정책:")
    assert by_session["bob"][0].startswith("배송")


def test_chatbot_iam_blocks_viewer(chatbot_dir):
    with LocalRunner(chatbot_dir) as r, pytest.raises(PermissionDenied) as e:
        r.order("search_result", {"q": "배송"}, requester="chatbot", context={"account": "viewer"})
    assert "order: chatbot → search_result" in e.value.blocked
