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
        chatbot("환불은 언제 되나요", session_id="carol")
        r.run_until_idle()
    assert by_session["alice"] == by_session["carol"]  # 같은 질문: 계산은 한 번, 답은 각자에게
    assert by_session["alice"][0].startswith("환불 정책:")
    assert by_session["bob"][0].startswith("배송")


def test_new_question_replaces_the_old_one_quietly(chatbot_dir):
    with LocalRunner(chatbot_dir) as r:
        chatbot = resolve_function(str(chatbot_dir / "chatbot.py"), "chatbot")
        by_session = chatbot.__globals__["BY_SESSION"]
        chatbot("배송 조회는 어디서 하나요", session_id="bob")
        chatbot("환불은 언제 되나요", session_id="bob")  # 첫 질문이 끝나기 전에 바꿈
        r.run_until_idle()
    assert len(by_session["bob"]) == 1 and by_session["bob"][0].startswith("환불 정책:")


def test_chatbot_iam_blocks_viewer(chatbot_dir):
    with LocalRunner(chatbot_dir) as r, pytest.raises(PermissionDenied) as e:
        r.order("search_result", {"q": "배송"}, requester="chatbot", context={"account": "viewer"})
    assert "order: chatbot → search_result" in e.value.blocked


def test_open_chat_gets_the_updated_answer_when_docs_change(chatbot_dir):
    docs = chatbot_dir / "sample_docs.json"
    with LocalRunner(chatbot_dir) as r:
        chatbot = resolve_function(str(chatbot_dir / "chatbot.py"), "chatbot")
        by_session = chatbot.__globals__["BY_SESSION"]
        chatbot("환불은 언제 되나요", session_id="alice")
        chatbot("배송 조회는 어디서 하나요", session_id="bob")
        r.run_until_idle()
        assert "7일" in by_session["alice"][-1]

        docs.write_text(docs.read_text("utf-8").replace("7일", "14일"), "utf-8")
        r.engine.invalidate(
            "search", "fetch", data_version="v2"
        )  # search.py의 watch_docs가 하는 일
        r.run_until_idle()

        assert by_session["alice"][-1].startswith("(갱신)") and "14일" in by_session["alice"][-1]
        assert len(by_session["bob"]) == 1  # 배송 답은 그대로라 다시 오지 않는다

        chatbot("회원 등급 혜택", session_id="alice")  # 새 질문 → 지난 구독은 끝난다
        r.run_until_idle()
        active = [s for s in r.engine.subscriptions("active") if s["meta"]["session_id"] == "alice"]
        assert len(active) == 1
