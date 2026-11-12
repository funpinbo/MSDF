# MSDF — Micro Service Data Flow

**한국어** | [English](README.en.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MSA 환경에서 **서비스끼리 서로를 몰라도 데이터를 주고받게** 하는 파이썬 프레임워크.

흐름의 기준이 task가 아니라 **데이터(Artifact)** 라는 점이 Airflow 같은 task 중심 도구와 다릅니다.
서비스는 "결과물 이름"만 요청하고, 그 뒤에 어떤 서비스가 어떤 순서로 붙는지는 DAG가 정합니다.

**왜 만들었나.** 챗봇을 에이전트로 만들다 보면 검색, 임베딩, 요약 같은 기능이 계속 붙고, 그때마다 챗봇이 "무엇을 어떤 순서로 부르고
결과를 어디에 두고 실패하면 어떻게 할지"까지 떠안게 됩니다. 게다가 챗봇은 데이터를 많이 바꿉니다. MSDF는 이 지휘 역할을 기능 밖으로 꺼내,
기능들이 서로를 모른 채 데이터 변화에 따라 움직이게 합니다. 그래서 기능을 더하거나 뺄 때 DAG만 고치면 됩니다. → [만든 이유](docs/background.md)

> 현재 버전 **0.1.0**: 한 머신에서 엔진과 여러 서비스 프로세스로 동작합니다. 아직 PyPI에는 없으며 [저장소나 git 주소로 설치](docs/installation.md)합니다.
> 남은 일은 [로드맵](docs/roadmap.md)에 있습니다.

## 빠르게 돌려 보기

```bash
git clone https://github.com/funpinbo/MSDF.git && cd MSDF
uv sync --all-extras
cd examples/chatbot
uv run python run_local.py "환불은 언제 되나요" "환불은 언제 되나요"
```

두 번째 질문은 같은 요청이라 단계를 하나도 실행하지 않고 캐시에서 답합니다. 엔진과 웹 UI까지 띄워 보려면 [시작하기](docs/getting-started.md)를 보세요.

## 어떻게 쓰나

```python
# app.py — 결과물 이름만 요청한다
from ms_dataflow import action, order, service, start

@service("app")
def app(day: str):
    order("daily_stats", params={"day": day})   # 즉시 반환, 결과를 기다리지 않는다

@action(inputs=["stats"])
def on_stats(stats): ...                         # DAG의 on_success가 가리킨다

@action
def on_stats_failed(status: str): ...            # DAG의 on_fail이 가리킨다

if __name__ == "__main__":
    start()        # 엔진에 붙는다 (바로 반환)
    app("2026-11-12")
```

```python
# transform.py — 자기 일만 선언한다
from ms_dataflow import action, service, start

@service("transform")
def transform(): ...

@action(inputs=["rows"], outputs=["clean"], retries=2)
def clean(rows): return [r for r in rows if r["value"] is not None]

@action(inputs=["rows"], outputs=["stats"])
def summarize(rows): return {"count": len(rows), "total": sum(r["value"] for r in rows)}

if __name__ == "__main__":
    start(block=True)   # Action만 제공하는 서비스는 Ctrl+C까지 기다린다
```

```yaml
# dags/daily_stats.yaml — 연결은 여기서만 바뀐다
order: daily_stats
nodes:
  load:      {service: source,    action: load, fresh_for: 1h}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}
edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}
result: summarize.stats
deliveries:
  - {requester: app, on_success: app.on_stats, on_fail: app.on_stats_failed}
```

```bash
msdf check           # 코드와 설정을 검증한다
msdf up              # 엔진(Scheduler + DB + 웹 UI)을 띄운다
python source.py     # 서비스는 평소대로 실행. start()가 엔진에 붙여 준다
python transform.py
python app.py
```

사용자가 쓰는 것은 `service`, `action`, `order`, `start`, `context`, `delete` 여섯 개와 YAML 세 개가 전부입니다.
데이터 ID, 캐시 키, 큐, lease, 직렬화는 엔진이 처리하며 사용자 코드에 나오지 않습니다.

## 무엇이 좋아지나

1. **저장소 선택이 자유롭다.** `resolvers.yaml`만 바꾼다. 서비스 코드는 어떤 DB인지 모른다.
2. **변경점이 최소화된다.** 로직이 바뀌면 서비스만, 흐름이 바뀌면 DAG만 고친다.
3. **데이터의 출처가 한눈에 보인다.** 모든 Artifact가 원본·서비스·Action·버전 계보를 들고 있다.
4. **권한을 한 곳에서 관리한다.** IAM 규칙 파일 하나가 모든 흐름을 검사한다.
5. **같은 요청은 다시 계산하지 않는다.** 로직을 고치면 그 단계부터만 다시 계산한다.
6. **실패한 곳부터 다시 시작한다.** 단계별로 저장되어 있고, 죽은 Worker의 일은 다른 인스턴스가 이어받는다.

## 무엇을 하지 않나

- 서비스 전체를 관리하지 않는다. 서비스 안의 맥락과 결과를 기다리는 방식은 작성자의 몫이다.
- 멱등성을 보장하지 않는다. 같은 입력에 같은 결과를 내는 것은 서비스의 책임이다.
- DB를 관리하지 않는다. 저장·삭제 요청을 보낼 뿐, 본체를 얼마나 보관할지는 사용자의 DB 설계 몫이다.

## 구조

```
          msdf up (엔진 프로세스)
   ┌──────────────────────────────┐
   │  Scheduler + Planner + IAM   │
   │  SQLite (유일한 작성자)      │
   │  웹 UI (/ui)                 │
   └──┬────────────┬──────────┬───┘
      │            │          │        HTTP 양방향
  ┌───┴────┐  ┌────┴─────┐  ┌─┴───────┐
  │  app   │  │  source  │  │transform│   각 프로세스 = 그 서비스의 Worker
  │+start()│  │ +start() │  │+start() │
  └────────┘  └──────────┘  └─────────┘
```

데이터 본체는 서비스 프로세스와 저장소 사이에서만 오갑니다. 엔진은 "어디에 넣을지"만 알려 주고 중계하지 않습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [만든 이유](docs/background.md) | 챗봇이 모든 로직을 떠안게 되는 문제와 MSDF의 접근 |
| [설치](docs/installation.md) | PyPI 없이 설치하는 세 가지 방법 (저장소, git 주소, 휠) |
| [시작하기](docs/getting-started.md) | 예제를 5분 만에 돌리고, 내 프로젝트에 붙이기 |
| [핵심 개념](docs/concepts.md) | Service, Action, Order, DAG, Artifact와 캐시·실패 처리 |
| [서비스 작성하기](docs/writing-services.md) | `service`, `action`, `order`, `start`, `context`, `delete` 사용법 |
| [설정 파일](docs/configuration.md) | DAG, IAM, resolvers YAML 문법, 로딩 검증, `msdf` 명령 |
| [내부 동작](docs/how-it-works.md) | 프로세스 구조, 단계 실행, 실패 처리, 보관과 삭제 |
| [로드맵](docs/roadmap.md) | 현재 상태, 방향, 다음에 할 것 |

예제: [`examples/chatbot`](examples/chatbot) — 서비스 넷을 LLM 없이 예시 문서로 연결한다.

## 설치

**아직 PyPI에 올리지 않았습니다.** 엔진을 띄우는 곳은 저장소를 받아 설치하고, 다른 저장소의 서비스는 git 주소로 설치합니다.

```bash
# 엔진을 띄우는 곳 (웹 UI 포함)
git clone https://github.com/funpinbo/MSDF.git && cd MSDF
uv sync --all-extras                     # pip라면: pip install -e ".[server]"

# 다른 저장소의 서비스
pip install "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git"
```

| 묶음 | 용도 |
| --- | --- |
| (없음) | 데코레이터, 모델, `msdf check` |
| `runtime` | `start()`로 엔진에 붙는 서비스 |
| `server` | `msdf up` (Scheduler + 웹 UI) |
| `dataframe` | DataFrame을 Parquet으로 저장 |

파이썬 3.11 이상. 패키지 이름은 `msdf`, import 이름은 항상 `ms_dataflow`입니다. 버전 고정, 휠 파일 만들기는 [설치](docs/installation.md)를 보세요.

## 웹 UI 빌드

`msdf up`은 `http://127.0.0.1:8787/ui`에 웹 UI를 띄웁니다. **UI는 소스만 저장소에 있고 빌드 결과는 없습니다.**
저장소를 받은 뒤 한 번 빌드하세요 (Node.js 20.19 이상, 22 권장).

```bash
cd frontend
npm install
npm run build        # 결과: ms_dataflow/ui/dist
```

빌드하지 않아도 엔진과 API는 그대로 동작하며, `/ui`가 위 명령을 안내합니다. git 주소로 설치한 곳에서는 빌드한 폴더를 `msdf up --ui-dist 경로`로 알려 줍니다.
화면 구성은 [frontend/README.md](frontend/README.md)를 보세요.

| 페이지 | 하는 일 |
| --- | --- |
| 실시간 맵 | 서비스·Action·데이터 흐름을 한 장의 그래프로, 성공·실패·캐시 수치와 함께 |
| DAG 편집기 | n8n처럼 Action 노드를 끌어다 놓고 연결해 DAG를 만들고 저장 |
| 로그 | 실행, 단계, 서비스, DAG, 엔진 로그를 나눠서 조회. 실패 원인과 데이터 계보 |

## 개발

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy ms_dataflow
```

기여 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)에 있습니다.

## 보안

엔진 API(`/api`, `/order` 등)와 웹 UI에는 **인증이 없습니다.** 기본으로 `127.0.0.1`에만 열리며, 다른 주소(`--host 0.0.0.0`)로 열 때는
믿을 수 있는 네트워크 안에서만 쓰세요. 웹 UI의 DAG 편집기는 엔진 머신의 `dags/` 파일을 고칠 수 있습니다.

## 라이선스

MIT. 자세한 내용은 [LICENSE](LICENSE)를 참고하세요.
