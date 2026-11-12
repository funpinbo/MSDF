# 시작하기

> **현재 상태: 구현 전.** 아래 명령과 코드는 목표하는 사용법이며 아직 동작하지 않습니다.

이 문서는 MSDF를 설치하고, 서비스 네 개가 데이터를 주고받는 흐름을 처음부터 끝까지 따라가 봅니다.
예제 파일은 모두 [`examples/chatbot`](../examples/chatbot)에 있습니다.

## 1. 설치

```bash
pip install 'msdf[server]'    # 엔진(msdf up)을 띄울 머신
pip install 'msdf[runtime]'   # start()로 엔진에 붙을 서비스
```

| 설치 방법 | 들어 있는 것 | 언제 |
| --- | --- | --- |
| `pip install msdf` | 데코레이터와 모델만 | 코드 작성, 타입 확인, 테스트 |
| `pip install 'msdf[runtime]'` | 위 + 엔진에 붙는 수신 서버 | 서비스를 실제로 돌릴 때 |
| `pip install 'msdf[server]'` | 위 + Scheduler와 웹 UI | `msdf up`을 실행할 때 |

파이썬 3.11 이상이 필요합니다. 패키지 이름은 `msdf`이고, 코드에서는 항상 `import ms_dataflow`로 씁니다.

## 2. 만들 흐름

챗봇이 사용자의 질문을 받으면, 검색 → 임베딩 → 가공을 거친 요약을 받아 답하는 흐름입니다.

```text
chatbot ──order("search_result")──▶ 엔진
                                      │ DAG를 보고 순서를 정한다
                                      ▼
            search.fetch ──▶ embedding.embed ──▶ processing.refine
                                                        │
chatbot.on_search_result ◀──────── 요약(summary) ────────┘
```

챗봇은 검색·임베딩·가공 서비스가 있다는 것을 모릅니다. `search_result`라는 이름만 압니다.

## 3. 서비스 작성

각 서비스는 자기 일만 선언합니다. `inputs`, `outputs`, `params`는 그 함수 안에서만 의미 있는 이름(슬롯)입니다.

```python
# search.py
from ms_dataflow import action, service, start

@service("search")
def search(): ...

@action(params=["q"], outputs=["out"], fresh_for="1d", retries=3)
def fetch(q: str): ...          # order의 params에서 q를 받는다. 하루 동안 캐시

if __name__ == "__main__":
    start()
```

```python
# embedding.py
@service("embedding")
def embedding(): ...

@action(inputs=["docs"], outputs=["out"], retries=3)
def embed(docs): ...
```

```python
# processing.py
@service("processing")
def processing(): ...

@action(inputs=["vectors"], outputs=["summary", "keywords"])
def refine(vectors): ...        # (summary, keywords) 순서로 반환
```

```python
# chatbot.py
from ms_dataflow import action, order, service, start

@service("chatbot")
def chatbot(question: str):
    order("search_result", params={"q": question})   # 즉시 반환. 결과를 기다리지 않는다

@action(inputs=["result"])
def on_search_result(result): ...    # 성공하면 여기로 요약이 도착한다

@action
def on_search_failed(status: str): ...   # "failed" 또는 "cancelled"

if __name__ == "__main__":
    start()      # 엔진에 붙는다 (바로 반환)
    app.run()    # 내 서비스는 평소대로 실행
```

## 4. 흐름 연결 (DAG)

서비스끼리의 연결은 코드가 아니라 DAG 파일에 적습니다.

```yaml
# dags/search_result.yaml
order: search_result              # 챗봇이 부르는 이름

nodes:
  fetch:  {service: search,     action: fetch, fresh_for: 1d}
  embed:  {service: embedding,  action: embed}
  refine: {service: processing, action: refine}

edges:
  - {from: fetch.out, to: embed.docs}
  - {from: embed.out, to: refine.vectors}

result: refine.summary            # 챗봇에게 돌려줄 슬롯

deliveries:
  - requester: chatbot
    on_success: chatbot.on_search_result
    on_fail:    chatbot.on_search_failed     # 필수
```

## 5. 권한과 저장소

권한 규칙(`iam.yaml`)과 저장 위치(`resolvers.yaml`)는 별도 파일입니다. 기본은 **거부**이므로, 흐름이 지나는 모든 연결을 허용해야 합니다.

```yaml
# iam.yaml
layers:
  service: {kind: flat, members: [chatbot, search, embedding, processing]}

rules:
  - {type: order, service: chatbot}
  - {type: flow, from: search.fetch,      to: embedding.embed,          account: any}
  - {type: flow, from: embedding.*,       to: processing.*,             account: any}
  - {type: flow, from: processing.refine, to: chatbot.on_search_result, account: any}
```

```yaml
# resolvers.yaml
default: {backend: file, path: ./store}    # 모든 데이터를 파일로 저장
```

예제의 [`iam.yaml`](../examples/chatbot/iam.yaml)은 계정 등급(`viewer`, `analyst`, `admin`)까지 쓰는 버전입니다. 자세한 문법은 [설정 파일](configuration.md)을 보세요.

## 6. 실행

```bash
msdf up                  # 터미널 1 — 엔진 (Scheduler + DB + 웹 UI)
python search.py         # 터미널 2
python embedding.py      # 터미널 3
python processing.py     # 터미널 4
python chatbot.py        # 터미널 5
```

`msdf up`은 설정 파일을 읽고 검증한 뒤 엔진만 띄웁니다. 서비스는 사용자가 평소대로 실행하며, `start()`가 그 프로세스를 엔진에 붙입니다.
설정에 오류가 있으면 이 시점에 파일, 줄, 원문, 이유, 고칠 방법을 함께 보여 주고 멈춥니다.

## 7. 확인

- 챗봇에 질문을 보내면 `on_search_result`가 요약을 받습니다.
- **같은 질문을 다시 보내면** 검색·임베딩·가공을 다시 하지 않고 저장된 결과를 바로 돌려줍니다(`fetch`는 하루 동안).
- `embed` 함수의 로직을 고치고 다시 띄우면, 검색 결과는 재사용하고 임베딩부터 다시 계산합니다.
- 웹 UI에서 DAG와 각 단계의 상태, 실패한 위치를 볼 수 있습니다.

## 다음

- 개념을 정리하고 싶다면 → [핵심 개념](concepts.md)
- 데코레이터 옵션을 전부 보고 싶다면 → [서비스 작성하기](writing-services.md)
