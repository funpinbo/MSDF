# 챗봇 예제

**한국어** | [English](README.en.md)

서비스 넷(chatbot, search, embedding, processing)이 서로를 모른 채 데이터를 주고받는 예제입니다.
**LLM이나 검색 엔진을 부르지 않습니다.** `sample_docs.json`의 예시 문서로 검색하고,
단어 빈도로 벡터를 흉내 내고, 첫 문장을 요약으로 씁니다. MSDF가 흐름을 어떻게 연결하는지 보여 주는 것이 목적입니다.

```text
chatbot ──order("search_result", q)──▶ 엔진
search.fetch(q) ─▶ embedding.embed ─▶ processing.refine ─▶ chatbot.on_search_result
```

저장소 루트에서 `uv sync --all-extras`를 한 뒤 이 폴더에서 실행합니다. pip로 설치했다면 가상 환경을 켜고 `uv run`을 빼세요.

## 한 프로세스로 빠르게 보기

```bash
uv run python run_local.py "환불은 언제 되나요" "환불은 언제 되나요"
```

두 번째 질문은 같은 요청이므로 단계를 하나도 실행하지 않고 캐시에서 답합니다.
이 데모는 자기 프로세스 안에 따로 엔진을 만들어 돌므로 **`msdf up`의 웹 UI에는 나타나지 않습니다.**

## 웹 UI에서 보기 (명령 두 개)

```bash
uv run msdf up                      # 터미널 1 — 엔진. http://127.0.0.1:8787/ui
uv run python run_services.py       # 터미널 2 — 서비스 넷을 엔진에 붙이고 예시 질문을 3초마다 보낸다
```

웹 UI의 실시간 맵, 로그에 실행이 바로 쌓입니다. Ctrl+C로 서비스를 모두 끕니다. 질문 간격은 `ASK_EVERY=1`처럼 바꿉니다.

## 여러 프로세스로 하나씩 실행

```bash
uv run msdf up                  # 터미널 1 — 엔진. http://127.0.0.1:8787/ui 에서 흐름을 볼 수 있다
uv run python search.py         # 터미널 2
uv run python embedding.py      # 터미널 3
uv run python processing.py     # 터미널 4
uv run python chatbot.py        # 터미널 5 — 질문을 입력한다 (빈 줄이면 종료)
```

웹 UI는 저장소 루트에서 한 번 빌드해야 보입니다: `cd frontend && npm install && npm run build`.

질문한 뒤 `sample_docs.json`의 답(예: "7일"을 "14일"로)을 고쳐 저장해 보세요. `search.py`가 바뀐 것을 알아채 `invalidate()`하고,
열려 있는 대화에 `(갱신)` 답이 다시 옵니다(챗봇은 `subscribe="10m"`로 묻습니다). 다른 질문의 답은 바뀌지 않았으므로 다시 오지 않습니다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `chatbot.py` | order를 내고 결과를 받는 서비스. `@context`로 계정 등급을 준다 |
| `search.py`, `embedding.py`, `processing.py` | 각자 Action 하나씩 |
| `dags/search_result.yaml` | 네 서비스를 잇는 DAG |
| `iam.yaml` | 계정 등급별 권한 |
| `resolvers.yaml` | 검색 결과는 SQLite, 나머지는 파일에 저장 |
| `sample_docs.json` | 예시 문서 |
| `run_local.py` | 프로세스 하나로 돌려 보는 데모 (자기 엔진, UI 없음) |
| `run_services.py` | 실행 중인 엔진에 서비스 넷을 붙이고 질문을 계속 보낸다 (UI용) |
