# MSDF 문서

**한국어** | [English](en/README.md)

MSDF(Micro Service Data Flow)는 마이크로서비스끼리 **서로를 몰라도** 데이터를 주고받게 해 주는 파이썬 프레임워크입니다.
서비스는 "이런 결과물이 필요하다"고 이름으로 요청만 하고, 그 결과물을 어느 서비스가 어떤 순서로 만드는지는 설정 파일(DAG)이 정합니다.

> 현재 버전: **0.3.0**. 한 머신에서 엔진과 여러 서비스 프로세스로 동작합니다. 아직 PyPI에는 없습니다([설치](installation.md)).
> 무엇이 되고 무엇이 남았는지는 [로드맵](roadmap.md)에 있습니다.

## 읽는 순서

| 순서 | 문서 | 이런 사람에게 |
| --- | --- | --- |
| – | [만든 이유](background.md) | 왜 이런 구조가 필요한지 먼저 알고 싶은 사람 |
| 0 | [설치](installation.md) | PyPI 없이 설치하기: 저장소, git 주소, 휠 파일 |
| 1 | [시작하기](getting-started.md) | 예제를 5분 만에 돌리고, 내 프로젝트에 붙이기 |
| 2 | [핵심 개념](concepts.md) | Service, Action, Order, DAG, Artifact가 무엇인지 알고 싶은 사람 |
| 3 | [서비스 작성하기](writing-services.md) | `service`, `action`, `order`, `start`, `context`, `delete`, `invalidate` 사용법 |
| 4 | [설정 파일](configuration.md) | DAG, IAM, resolvers 세 YAML 파일과 `msdf` 명령 |
| 5 | [내부 동작](how-it-works.md) | 엔진이 요청을 어떻게 처리하는지, 실패하면 어떻게 되는지 |
| 6 | [로드맵](roadmap.md) | 어디까지 만들어졌고 어떤 방향으로 가는지 |

## 한눈에 보기

```python
# app.py — 서비스는 결과물 이름만 요청한다
from ms_dataflow import action, order, service

@service("app")
def app(day: str, user: str):
    order("daily_stats", params={"day": day}, meta={"user": user})   # 즉시 반환. request_id를 돌려준다

@action(inputs=["stats"])
def on_stats(stats, meta):                       # 결과가 도착하면 깨워진다. meta로 누구의 요청인지 안다
    print(meta["user"], "에게:", stats)

@action
def on_stats_failed(status: str):                # 최종 실패하면 깨워진다
    print("실패:", status)
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
