# 시작하기

이 문서는 MSDF를 설치하고, 서비스 셋이 데이터를 주고받는 흐름을 처음부터 끝까지 만들어 봅니다.
예시는 "하루치 데이터를 읽어(`source`) → 정리하고 집계해(`transform`) → 요청한 쪽(`app`)에 돌려준다"입니다.

## 1. 설치

```bash
pip install 'msdf[server]'    # 엔진(msdf up)을 띄울 곳
pip install 'msdf[runtime]'   # start()로 엔진에 붙을 서비스
```

| 설치 방법 | 들어 있는 것 | 언제 |
| --- | --- | --- |
| `pip install msdf` | 데코레이터, 모델, 정적 분석 | 코드 작성, `msdf check` |
| `pip install 'msdf[runtime]'` | 위 + 엔진에 붙는 수신 서버 | 서비스를 실제로 돌릴 때 |
| `pip install 'msdf[server]'` | 위 + Scheduler와 웹 UI | `msdf up`을 실행할 때 |
| `pip install 'msdf[dataframe]'` | pandas, pyarrow | DataFrame을 주고받을 때 (Parquet 저장) |

파이썬 3.11 이상이 필요합니다. 패키지 이름은 `msdf`이고, 코드에서는 항상 `import ms_dataflow`로 씁니다.

## 2. 프로젝트 구조

```text
my_project/
├── source.py
├── transform.py
├── app.py
├── dags/
│   └── daily_stats.yaml
├── iam.yaml          # 없어도 된다 (그러면 권한 검사를 하지 않는다)
└── resolvers.yaml    # 없어도 된다 (그러면 .msdf/store에 파일로 저장한다)
```

## 3. 서비스 작성

각 서비스는 자기 일만 선언합니다. `inputs`, `outputs`, `params`는 그 함수 안에서만 의미 있는 이름(슬롯)입니다.

```python
# source.py
from ms_dataflow import action, service, start

@service("source")
def source(): ...

@action(params=["day"], outputs=["rows"], fresh_for="1h")
def load(day: str) -> list:
    # 실제로는 DB나 외부 API에서 읽는다
    return [{"day": day, "value": v} for v in (3, None, 7, 5)]

if __name__ == "__main__":
    start()
    input("source 실행 중. Enter로 종료\n")
```

```python
# transform.py
from ms_dataflow import action, service, start

@service("transform")
def transform(): ...

@action(inputs=["rows"], outputs=["clean"], retries=2)
def clean(rows: list) -> list:
    return [r for r in rows if r["value"] is not None]

@action(inputs=["rows"], outputs=["stats"])
def summarize(rows: list) -> dict:
    values = [r["value"] for r in rows]
    return {"count": len(values), "total": sum(values)}

if __name__ == "__main__":
    start()
    input("transform 실행 중. Enter로 종료\n")
```

```python
# app.py
from ms_dataflow import action, order, service, start

@service("app")
def app(day: str):
    order("daily_stats", params={"day": day})   # 즉시 반환. 결과를 기다리지 않는다

@action(inputs=["stats"])
def on_stats(stats: dict):
    print("결과:", stats)

@action
def on_stats_failed(status: str):   # "failed" 또는 "cancelled"
    print("실패:", status)

if __name__ == "__main__":
    start()                          # 엔진에 붙는다 (바로 반환)
    app("2026-11-12")
    input("결과를 기다리는 중. Enter로 종료\n")
```

## 4. 흐름 연결 (DAG)

서비스끼리의 연결은 코드가 아니라 DAG 파일에 적습니다.

```yaml
# dags/daily_stats.yaml
order: daily_stats               # app이 부르는 이름

nodes:
  load:      {service: source,    action: load}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}

edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}

result: summarize.stats          # app에게 돌려줄 슬롯

deliveries:
  - requester: app
    on_success: app.on_stats
    on_fail:    app.on_stats_failed   # 필수
```

## 5. 검증

```bash
msdf check
```

코드와 설정 파일을 읽어 잘못된 곳을 모두 모아 보여 줍니다. 예를 들어 DAG가 없는 Action을 가리키면 이렇게 나옵니다.

```text
MSDF 로딩 오류: dags/daily_stats.yaml
  노드 'clean': 서비스 'transform'에 Action 'cleaning'이 없습니다.
  고칠 방법: 있는 Action: clean, summarize
```

## 6. 실행

```bash
msdf up                  # 터미널 1 — 엔진 (Scheduler + DB + 웹 UI)
python source.py         # 터미널 2
python transform.py      # 터미널 3
python app.py            # 터미널 4
```

`msdf up`은 설정을 읽고 검증한 뒤 엔진만 띄웁니다. 서비스는 평소대로 실행하고, `start()`가 그 프로세스를 엔진에 붙입니다.
`app.py`가 `결과: {'count': 3, 'total': 15}`를 출력하면 성공입니다.

## 7. 확인

- 브라우저에서 `http://127.0.0.1:8787/ui`를 열면 DAG, 각 단계의 상태, 실패한 위치와 원인을 볼 수 있습니다.
- **같은 날짜로 다시 요청하면** 세 단계를 다시 하지 않고 저장된 결과를 바로 돌려줍니다(`load`는 1시간 동안).
- `summarize` 함수의 로직을 고치고 `transform.py`를 다시 띄우면, `load`와 `clean` 결과는 재사용하고 `summarize`부터 다시 계산합니다. 주석이나 공백만 바꾼 것은 로직 변경으로 보지 않습니다.
- 실행 중에 `transform.py`를 죽이고 다시 띄우면, 하던 단계가 다시 배정되어 이어집니다.

## 8. 권한 붙이기 (선택)

`iam.yaml`을 두면 기본이 **거부**가 되고, 허용한 것만 통과합니다.

```yaml
# iam.yaml
rules:
  - {type: order, service: app}
  - {type: flow, from: source.load,     to: transform.clean}
  - {type: flow, from: transform.clean, to: transform.summarize}
  - {type: flow, from: transform.summarize, to: app.on_stats}
```

계정 등급 같은 계층을 쓰는 방법은 [설정 파일](configuration.md#iam-파일)을 보세요.

## 프로세스 하나로 시험하기

테스트에서는 엔진과 서비스를 한 프로세스에서 돌리는 `LocalRunner`를 쓸 수 있습니다.

```python
from ms_dataflow.execute.local import LocalRunner

with LocalRunner("my_project") as runner:
    runner.order("daily_stats", {"day": "2026-11-12"}, requester="app")
    runner.run_until_idle()
```

## 다음

- 개념을 정리하고 싶다면 → [핵심 개념](concepts.md)
- 데코레이터 옵션을 전부 보고 싶다면 → [서비스 작성하기](writing-services.md)
