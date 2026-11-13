"""챗봇 서비스. 질문을 받으면 search_result를 order하고, 결과가 오면 답한다.

LLM을 부르지 않는다. 다른 서비스가 만든 요약을 그대로 답으로 쓴다.
"""

from ms_dataflow import action, cancel, context, order, service, start

ANSWERS: list[str] = []
# 사용자(세션)별 답. 여러 사용자가 동시에 물어도 섞이지 않는다
BY_SESSION: dict[str, list[str]] = {}
OPEN: dict[str, str] = {}  # 세션 → 지금 구독 중인 request_id (세션마다 마지막 질문 하나만)


@context
def who() -> dict:
    # 실제 서비스라면 로그인한 사용자의 등급을 돌려준다. 예제는 고정값.
    return {"account": "analyst"}


@service("chatbot")
def chatbot(question: str, session_id: str = "local") -> str:
    # 즉시 반환. 결과를 기다리지 않는다.
    # params는 "무엇을 계산할지"(cache key), meta는 "결과를 누구에게 돌려줄지"(cache key 아님).
    # 그래서 두 사용자가 같은 질문을 하면 계산은 한 번, 답은 각자에게 간다.
    # subscribe: 대화가 열려 있는 동안 문서가 바뀌면 새 답을 다시 받는다.
    if session_id in OPEN:
        cancel(OPEN.pop(session_id))  # 새 질문을 하면 지난 질문의 구독은 끝낸다
    request_id = order(
        "search_result",
        params={"q": question},
        meta={"session_id": session_id},
        subscribe="10m",
    )
    OPEN[session_id] = request_id
    return request_id


def _answer(session_id: str, text: str) -> None:
    ANSWERS.append(text)
    BY_SESSION.setdefault(session_id, []).append(text)
    print(f"[챗봇 → {session_id}] {text}", flush=True)


@action(inputs=["result"])
def on_search_result(result: str, meta: dict, refresh: int):  # DAG의 on_success가 가리킨다
    # refresh > 0: 문서가 바뀌어 다시 계산한 답 (같은 답이면 오지 않는다)
    _answer(meta.get("session_id", "local"), result if refresh == 0 else f"(갱신) {result}")


@action
def on_search_failed(status: str, meta: dict, error: str | None, request_id: str):
    session = meta.get("session_id", "local")
    if status == "cancelled" and OPEN.get(session) != request_id:
        return  # 새 질문을 하면서 우리가 취소한 요청이다. 사용자에게 알릴 것이 없다
    _answer(session, f"죄송합니다. 답을 만들지 못했습니다 ({status}).")
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
