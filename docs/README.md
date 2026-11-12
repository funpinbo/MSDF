# MSDF 문서

> **현재 상태: 구현 전.** 이 문서들은 MSDF가 완성되었을 때의 사용법과 동작을 설명합니다.
> 아직 코드가 동작하지 않으며, 어디까지 만들어졌는지는 [로드맵](roadmap.md)에서 확인하세요.

MSDF(Micro Service Data Flow)는 마이크로서비스끼리 **서로를 몰라도** 데이터를 주고받게 해 주는 파이썬 프레임워크입니다.
서비스는 "이런 결과물이 필요하다"고 이름으로 요청만 하고, 그 결과물을 어느 서비스가 어떤 순서로 만드는지는 설정 파일(DAG)이 정합니다.

## 읽는 순서

| 순서 | 문서 | 이런 사람에게 |
| --- | --- | --- |
| 1 | [시작하기](getting-started.md) | 처음 써 보는 사람. 설치부터 첫 흐름을 돌리기까지 |
| 2 | [핵심 개념](concepts.md) | Service, Action, Order, DAG, Artifact가 무엇인지 알고 싶은 사람 |
| 3 | [서비스 작성하기](writing-services.md) | 데코레이터와 함수(`service`, `action`, `order`, `start`, `context`)의 사용법 |
| 4 | [설정 파일](configuration.md) | DAG, IAM, resolvers 세 YAML 파일을 쓰는 사람 |
| 5 | [내부 동작](how-it-works.md) | 엔진이 요청을 어떻게 처리하는지, 실패하면 어떻게 되는지 궁금한 사람 |
| 6 | [로드맵](roadmap.md) | 어디까지 만들어졌고 어떤 방향으로 가는지 |

## 한눈에 보기

```python
# chatbot.py — 서비스는 결과물 이름만 요청한다
from ms_dataflow import service, action, order, start

@service("chatbot")
def chatbot(question: str):
    order("search_result", params={"q": question})   # 즉시 반환

@action(inputs=["result"])
def on_search_result(result): ...                    # 결과가 도착하면 깨워진다

@action
def on_search_failed(status: str): ...               # 최종 실패하면 깨워진다
```

```yaml
# dags/search_result.yaml — 누가 어떤 순서로 만드는지는 여기서만 정한다
order: search_result
nodes:
  fetch:  {service: search,     action: fetch}
  embed:  {service: embedding,  action: embed}
  refine: {service: processing, action: refine}
edges:
  - {from: fetch.out, to: embed.docs}
  - {from: embed.out, to: refine.vectors}
result: refine.summary
deliveries:
  - {requester: chatbot, on_success: chatbot.on_search_result, on_fail: chatbot.on_search_failed}
```

챗봇 코드에는 `search`, `embedding`, `processing`이라는 이름도, 데이터가 어느 DB에 있는지도 나오지 않습니다.
흐름이 바뀌면 DAG만, 로직이 바뀌면 해당 서비스만 고치면 됩니다.

전체 예제는 [`examples/chatbot`](../examples/chatbot)에 있습니다.
