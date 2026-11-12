"""챗봇 서비스. 질문을 받으면 search_result를 order하고, 결과가 오면 답한다.

LLM을 부르지 않는다. 다른 서비스가 만든 요약을 그대로 답으로 쓴다.
"""

from ms_dataflow import action, context, order, service, start

ANSWERS: list[str] = []


@context
def who() -> dict:
    # 실제 서비스라면 로그인한 사용자의 등급을 돌려준다. 예제는 고정값.
    return {"account": "analyst"}


@service("chatbot")
def chatbot(question: str):
    order("search_result", params={"q": question})  # 즉시 반환. 결과를 기다리지 않는다


@action(inputs=["result"])
def on_search_result(result: str):  # DAG의 on_success가 가리킨다
    ANSWERS.append(result)
    print(f"[챗봇] {result}", flush=True)


@action
def on_search_failed(status: str):  # "failed" | "cancelled"
    ANSWERS.append(f"죄송합니다. 답을 만들지 못했습니다 ({status}).")
    print(f"[챗봇] 실패: {status}", flush=True)


if __name__ == "__main__":
    start()
    print("질문을 입력하세요 (빈 줄이면 종료)")
    while q := input("> ").strip():
        chatbot(q)
