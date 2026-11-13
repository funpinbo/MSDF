"""챗봇 서비스. 질문을 받으면 search_result를 order하고, 결과가 오면 답한다.

LLM을 부르지 않는다. 다른 서비스가 만든 요약을 그대로 답으로 쓴다.
"""

from ms_dataflow import action, context, order, service, start

ANSWERS: list[str] = []
# 사용자(세션)별 답. 여러 사용자가 동시에 물어도 섞이지 않는다
BY_SESSION: dict[str, list[str]] = {}


@context
def who() -> dict:
    # 실제 서비스라면 로그인한 사용자의 등급을 돌려준다. 예제는 고정값.
    return {"account": "analyst"}


@service("chatbot")
def chatbot(question: str, session_id: str = "local") -> str:
    # 즉시 반환. 결과를 기다리지 않는다.
    # params는 "무엇을 계산할지"(cache key), meta는 "결과를 누구에게 돌려줄지"(cache key 아님).
    # 그래서 두 사용자가 같은 질문을 하면 계산은 한 번, 답은 각자에게 간다.
    return order("search_result", params={"q": question}, meta={"session_id": session_id})


def _answer(session_id: str, text: str) -> None:
    ANSWERS.append(text)
    BY_SESSION.setdefault(session_id, []).append(text)
    print(f"[챗봇 → {session_id}] {text}", flush=True)


@action(inputs=["result"])
def on_search_result(result: str, meta: dict):  # DAG의 on_success가 가리킨다
    _answer(meta.get("session_id", "local"), result)


@action
def on_search_failed(status: str, meta: dict, error: str | None):  # "failed" | "cancelled"
    _answer(meta.get("session_id", "local"), f"죄송합니다. 답을 만들지 못했습니다 ({status}).")
    if error:
        print(f"  원인: {error}", flush=True)


if __name__ == "__main__":
    import time

    start()
    print("질문을 입력하세요 (빈 줄이면 종료)")
    try:
        while q := input("> ").strip():
            chatbot(q)
    except (EOFError, KeyboardInterrupt):
        pass
    time.sleep(2)  # 아직 오지 않은 답을 잠깐 기다린다
