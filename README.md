# MSDF — Micro Service Data Flow

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MSA 환경에서 **서비스끼리 서로를 몰라도 데이터를 주고받게** 하는 파이썬 프레임워크.

흐름의 기준이 task가 아니라 **데이터(Artifact)** 라는 점이 Airflow 같은 task 중심 도구와 다릅니다.
서비스는 "결과물 이름"만 요청하고, 그 뒤에 어떤 서비스가 어떤 순서로 붙는지는 DAG가 정합니다.

> 현재 상태: **설계 완료, 구현 시작 전.** 아래 코드는 목표하는 API이며 아직 동작하지 않습니다.

## 어떻게 쓰나

```python
# chatbot.py
from ms_dataflow import service, action, order, start

@service("chatbot")
def chatbot(question: str):
    key = order("search_result", params={"q": question})   # 즉시 반환, 비동기
    ...                                                    # 결과를 기다리지 않고 다른 일을 한다

@action(inputs=["result"])
def on_search_result(result): ...        # DAG의 on_success가 가리킨다

@action
def on_search_failed(status: str): ...   # DAG의 on_fail이 가리킨다

if __name__ == "__main__":
    start()        # 엔진에 붙는다 (논블로킹)
    app.run()      # 내 서비스는 평소대로
```

```yaml
# dags/search_result.yaml — 연결은 여기서만 바뀐다
order: search_result

nodes:
  fetch:  {service: search,     action: fetch, fresh_for: 1d}
  embed:  {service: embedding,  action: embed}
  refine: {service: processing, action: refine}

edges:
  - {from: fetch.out, to: embed.docs}
  - {from: embed.out, to: refine.vectors}

result: refine.summary

deliveries:
  - requester: chatbot
    on_success: chatbot.on_search_result
    on_fail:    chatbot.on_search_failed
```

```bash
msdf up          # 엔진(Scheduler + DB + 로컬 웹 UI)을 띄운다
python chatbot.py   # 서비스는 평소대로 실행. start()가 엔진에 붙여 준다
```

사용자가 쓰는 것은 `service`, `action`, `order`, `start`, `context` 다섯 개와 YAML 세 개가 전부입니다.
artifact id, 캐시 키, 큐, lease, 직렬화는 엔진이 처리하며 사용자 코드에 나오지 않습니다.

## 무엇이 좋아지나

1. **DB 선택이 자유롭다.** Resolver 설정만 바꾼다. 서비스 코드는 어떤 DB인지 모른다.
2. **변경점이 최소화된다.** 로직이 바뀌면 서비스만, 흐름이 바뀌면 DAG만 고친다.
3. **데이터의 출처가 한눈에 보인다.** 모든 Artifact가 원본·서비스·action 계보를 들고 있다.
4. **권한을 한 곳에서 관리한다.** IAM 규칙 파일 하나가 모든 흐름을 검사한다.
5. **자주 쓰는 데이터는 재사용한다.** 같은 요청이면 계산하지 않고 기존 Artifact를 돌려준다.
6. **재시작 위치가 자유롭다.** 단계별로 저장되어 있어 실패한 단계부터 다시 시작한다.

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
   │  로컬 웹 UI (Vue)            │
   └──┬────────────┬──────────┬───┘
      │            │          │        HTTP 양방향
  ┌───┴────┐  ┌────┴───┐  ┌───┴─────┐
  │chatbot │  │ search │  │embedding│   각 프로세스 = 그 서비스의 Worker
  │+start()│  │+start()│  │+start() │
  └────────┘  └────────┘  └─────────┘
```

데이터 본체는 서비스 프로세스와 저장소 사이에서만 오갑니다. 엔진은 "어디에 넣을지"만 알려 주고 중계하지 않습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [시작하기](docs/getting-started.md) | 설치부터 첫 흐름을 돌리기까지 |
| [핵심 개념](docs/concepts.md) | Service, Action, Order, DAG, Artifact와 캐시·실패 처리 |
| [서비스 작성하기](docs/writing-services.md) | `service`, `action`, `order`, `start`, `context` 사용법 |
| [설정 파일](docs/configuration.md) | DAG, IAM, resolvers YAML 문법과 로딩 검증 |
| [내부 동작](docs/how-it-works.md) | 프로세스 구조, 단계 실행, 실패 처리, 저장소 |
| [로드맵](docs/roadmap.md) | 현재 상태, 방향, 구현 순서, 미정 항목 |

## 설치

```bash
pip install msdf              # 코어 (데코레이터와 모델만)
pip install 'msdf[runtime]'   # start()로 엔진에 붙는 서비스
pip install 'msdf[server]'    # msdf up (Scheduler + UI)
```

패키지 이름은 `msdf`, import 이름은 항상 `ms_dataflow`입니다.

## 개발

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```

## 라이선스

MIT. 자세한 내용은 [LICENSE](LICENSE)를 참고하세요.
