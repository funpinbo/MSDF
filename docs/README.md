# MSDF 문서

MSDF(Micro Service Data Flow)는 마이크로서비스끼리 **서로를 몰라도** 데이터를 주고받게 해 주는 파이썬 프레임워크입니다.
서비스는 "이런 결과물이 필요하다"고 이름으로 요청만 하고, 그 결과물을 어느 서비스가 어떤 순서로 만드는지는 설정 파일(DAG)이 정합니다.

> 현재 버전: **0.1.0**. 한 머신에서 엔진과 여러 서비스 프로세스로 동작합니다. 무엇이 되고 무엇이 남았는지는 [로드맵](roadmap.md)에 있습니다.

## 읽는 순서

| 순서 | 문서 | 이런 사람에게 |
| --- | --- | --- |
| 1 | [시작하기](getting-started.md) | 처음 써 보는 사람. 설치부터 첫 흐름을 돌리기까지 |
| 2 | [핵심 개념](concepts.md) | Service, Action, Order, DAG, Artifact가 무엇인지 알고 싶은 사람 |
| 3 | [서비스 작성하기](writing-services.md) | `service`, `action`, `order`, `start`, `context`, `delete` 사용법 |
| 4 | [설정 파일](configuration.md) | DAG, IAM, resolvers 세 YAML 파일과 `msdf` 명령 |
| 5 | [내부 동작](how-it-works.md) | 엔진이 요청을 어떻게 처리하는지, 실패하면 어떻게 되는지 |
| 6 | [로드맵](roadmap.md) | 어디까지 만들어졌고 어떤 방향으로 가는지 |

## 한눈에 보기

```python
# app.py — 서비스는 결과물 이름만 요청한다
from ms_dataflow import action, order, service

@service("app")
def app(day: str):
    order("daily_stats", params={"day": day})   # 즉시 반환

@action(inputs=["stats"])
def on_stats(stats): ...                         # 결과가 도착하면 깨워진다

@action
def on_stats_failed(status: str): ...            # 최종 실패하면 깨워진다
```

```yaml
# dags/daily_stats.yaml — 누가 어떤 순서로 만드는지는 여기서만 정한다
order: daily_stats
nodes:
  load:      {service: source,    action: load}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}
edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}
result: summarize.stats
deliveries:
  - {requester: app, on_success: app.on_stats, on_fail: app.on_stats_failed}
```

`app` 코드에는 `source`, `transform`이라는 이름도, 데이터가 어느 DB에 있는지도 나오지 않습니다.
흐름이 바뀌면 DAG만, 로직이 바뀌면 해당 서비스만 고치면 됩니다.

실제로 돌려 볼 수 있는 예제는 [`examples/chatbot`](../examples/chatbot)에 있습니다. LLM 없이 예시 문서로 동작합니다.
