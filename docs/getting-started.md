# 시작하기

**한국어** | [English](en/getting-started.md)

두 단계로 나눠 봅니다.

1. **예제를 5분 만에 돌려 보기** — 저장소에 있는 챗봇 예제(LLM 없이 예시 문서로 동작)를 엔진과 함께 띄웁니다.
2. **내 프로젝트에 붙이기** — 서비스 셋을 직접 만들어 연결합니다.

MSDF는 아직 PyPI에 없습니다. 설치 방법은 [설치](installation.md)에 정리되어 있고, 여기서는 저장소를 받아 쓰는 방법을 씁니다.

## 1. 예제를 5분 만에 돌려 보기

### 준비

```bash
git clone https://github.com/funpinbo/MSDF.git
cd MSDF
uv sync --all-extras                       # pip라면: pip install -e ".[server]"
(cd frontend && npm install && npm run build)   # 웹 UI (Node.js 20.19 이상)
```

> 아래 명령의 `uv run`은 저장소의 가상 환경에서 실행하라는 뜻입니다. pip로 설치했다면 가상 환경을 켜고 `uv run`을 빼세요.

### 프로세스 하나로 보기

```bash
cd examples/chatbot
uv run python run_local.py "환불은 언제 되나요" "배송 조회는 어디서" "환불은 언제 되나요"
```

```text
> 환불은 언제 되나요
[챗봇] 환불 정책: 구매 후 7일 이내에는 전액 환불됩니다.
  실행한 단계: fetch, embed, refine
...
> 환불은 언제 되나요
[챗봇] 환불 정책: 구매 후 7일 이내에는 전액 환불됩니다.
  실행한 단계: 없음 (캐시: fetch, embed, refine)
```

같은 질문을 다시 하면 세 단계를 하나도 실행하지 않고 저장된 결과로 답합니다.

> `run_local.py`는 자기 프로세스 안에 따로 엔진과 DB를 만들어 돌고 끝납니다. 그래서 **`msdf up`의 웹 UI에는 나타나지 않습니다.**
> UI에서 보려면 아래처럼 엔진을 띄우고 서비스를 그 엔진에 붙여야 합니다.

### 웹 UI에서 보기

`examples/chatbot` 폴더에서 터미널 두 개를 엽니다.

```bash
uv run msdf up                      # 터미널 1 — 엔진 (Scheduler + DB + 웹 UI)
```

```bash
uv run python run_services.py       # 터미널 2 — 서비스 넷을 엔진에 붙이고 예시 질문을 3초마다 보낸다
```

브라우저에서 `http://127.0.0.1:8787/ui`를 열면 실행이 바로 쌓이기 시작합니다. Ctrl+C로 서비스를 모두 끕니다.

### 엔진과 서비스를 하나씩 띄우기

실제로 쓸 때의 모습입니다. 서비스마다 자기 프로세스로 띄웁니다. `examples/chatbot` 폴더에서 터미널 다섯 개를 엽니다.

```bash
uv run msdf up                  # 터미널 1 — 엔진 (Scheduler + DB + 웹 UI)
```

```bash
uv run python search.py         # 터미널 2
```

```bash
uv run python embedding.py      # 터미널 3
```

```bash
uv run python processing.py     # 터미널 4
```

```bash
uv run python chatbot.py        # 터미널 5 — 질문을 입력한다
```

브라우저에서 `http://127.0.0.1:8787/ui`를 엽니다. 엔진이 원격 서버나 VM에서 돈다면 내 컴퓨터에서 `ssh -L 8787:127.0.0.1:8787 사용자@서버`로 터널을 연 뒤 같은 주소를 엽니다([문제가 생기면](installation.md#문제가-생기면)).

- **실시간 맵**: 네 서비스와 데이터 흐름, 단계별 성공·실패·캐시 수가 2초마다 갱신됩니다.
- **DAG 편집기**: `search_result` DAG를 그래프로 보고 고칠 수 있습니다.
- **로그**: 질문 하나하나가 실행(run)으로 남고, 단계마다 걸린 시간과 오류를 볼 수 있습니다.

`embedding.py`를 실행 중에 Ctrl+C로 끄고 다시 띄우면, 하던 단계가 다시 배정되어 이어집니다.

## 2. 내 프로젝트에 붙이기

예시는 "하루치 데이터를 읽어(`source`) → 정리하고 집계해(`transform`) → 요청한 쪽(`app`)에 돌려준다"입니다.

> **빠른 길**: `msdf init my_project`가 아래와 같은 구성의 파일을 만들어 줍니다(iam.yaml 포함). 만든 뒤 `cd my_project`에서 [실행](#실행)으로 건너뛰어도 됩니다.

### 프로젝트 구조

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

MSDF 설치는 [설치](installation.md)를 보세요. 이 프로젝트가 별도 저장소라면 `pip install "msdf[server] @ git+https://github.com/funpinbo/MSDF.git"`로도 됩니다.

### 서비스 작성

각 서비스는 자기 일만 선언합니다. `inputs`, `outputs`, `params`는 그 함수 안에서만 의미 있는 이름(슬롯)입니다.

```python
# source.py
from ms_dataflow import action, service, start

service("source")

@action(params=["day"], outputs=["rows"], fresh_for="1h")
def load(day: str) -> list:
    # 실제로는 DB나 외부 API에서 읽는다
    return [{"day": day, "value": v} for v in (3, None, 7, 5)]

if __name__ == "__main__":
    start(block=True)   # 엔진에 붙고, Ctrl+C로 끌 때까지 단계를 처리한다
```

```python
# transform.py
from ms_dataflow import action, service, start

service("transform")

@action(inputs=["rows"], outputs=["clean"], retries=2)
def clean(rows: list) -> list:
    return [r for r in rows if r["value"] is not None]

@action(inputs=["rows"], outputs=["stats"])
def summarize(rows: list) -> dict:
    values = [r["value"] for r in rows]
    return {"count": len(values), "total": sum(values)}

if __name__ == "__main__":
    start(block=True)
```

```python
# app.py
import time

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
    time.sleep(3)                    # 실제 서비스라면 자기 서버(app.run() 등)가 계속 돈다
```

`start()`는 바로 반환하므로, 웹 서버처럼 자기 메인 루프가 있는 서비스는 그 뒤에 평소대로 실행하면 됩니다.
Action만 제공하는 서비스는 `start(block=True)`로 프로세스를 살려 둡니다.

### 흐름 연결 (DAG)

서비스끼리의 연결은 코드가 아니라 DAG 파일에 적습니다. 웹 UI의 DAG 편집기에서 노드를 끌어다 놓아 만들어도 같은 파일이 저장됩니다.

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

### 검증

```bash
msdf check
```

코드와 설정 파일을 읽어 잘못된 곳을 모두 모아 보여 줍니다. 예를 들어 DAG가 없는 Action을 가리키면 이렇게 나옵니다.

```text
MSDF 로딩 오류: dags/daily_stats.yaml
  노드 'clean': 서비스 'transform'에 Action 'cleaning'이 없습니다.
  고칠 방법: 있는 Action: clean, summarize
```

### 실행

```bash
msdf up                  # 터미널 1 — 엔진
python source.py         # 터미널 2
python transform.py      # 터미널 3
python app.py            # 터미널 4
```

`msdf up`은 설정을 읽고 검증한 뒤 엔진만 띄웁니다. 서비스는 평소대로 실행하고, `start()`가 그 프로세스를 엔진에 붙입니다.
`app.py`가 `결과: {'count': 3, 'total': 15}`를 출력하면 성공입니다.

엔진 주소를 바꿨다면 서비스에서 `start("http://호스트:포트")`나 환경 변수 `MSDF_SCHEDULER`로 알려 줍니다.

### 확인

- `http://127.0.0.1:8787/ui`에서 흐름과 수치, 로그를 봅니다. 터미널에서는 `msdf status`, `msdf runs`.
- **같은 날짜로 다시 요청하면** 세 단계를 다시 하지 않고 저장된 결과를 바로 돌려줍니다(`load`는 1시간 동안).
- `summarize` 함수의 로직을 고치고 `transform.py`를 다시 띄우면, `load`와 `clean` 결과는 재사용하고 `summarize`부터 다시 계산합니다. 주석이나 공백만 바꾼 것은 로직 변경으로 보지 않습니다.
- 실행 중에 `transform.py`를 죽이고 다시 띄우면, 하던 단계가 다시 배정되어 이어집니다.

### 권한 붙이기 (선택)

`iam.yaml`을 두면 기본이 **거부**가 되고, 허용한 것만 통과합니다.

```yaml
# iam.yaml
rules:
  - {type: order, service: app}
  - {type: flow, from: source.load,         to: transform.clean}
  - {type: flow, from: transform.clean,     to: transform.summarize}
  - {type: flow, from: transform.summarize, to: app.on_stats}
```

계정 등급 같은 계층을 쓰는 방법은 [설정 파일](configuration.md#iam-파일)을 보세요.

### 프로세스 하나로 시험하기

테스트에서는 엔진과 서비스를 한 프로세스에서 돌리는 `LocalRunner`를 쓸 수 있습니다.

```python
from ms_dataflow.execute.local import LocalRunner

with LocalRunner("my_project") as runner:
    runner.order("daily_stats", {"day": "2026-11-12"}, requester="app")
    runner.run_until_idle()
```

## 다음

- 개념을 정리하고 싶다면 → [핵심 개념](concepts.md)
- 데코레이터와 함수의 옵션 전부 → [서비스 작성하기](writing-services.md)
- 엔진 명령과 YAML 문법 → [설정 파일](configuration.md)
