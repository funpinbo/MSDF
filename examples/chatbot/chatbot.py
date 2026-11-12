from ms_dataflow import action, order, service, start


@service("chatbot")
def chatbot(question: str):
    order("search_result", params={"q": question})   # 즉시 반환, 비동기
    ...                                              # 결과를 기다리지 않고 다른 일을 한다


@action(inputs=["result"])
def on_search_result(result): ...        # DAG의 on_success가 가리킨다


@action
def on_search_failed(status: str): ...   # "failed" | "cancelled"


if __name__ == "__main__":
    start()      # 엔진에 붙는다 (논블로킹)
    # app.run()  # 내 서비스는 평소대로
