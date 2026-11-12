# 챗봇 예제

서비스 넷(chatbot, search, embedding, processing)이 서로를 모른 채 데이터를 주고받는 예제입니다.
**LLM이나 검색 엔진을 부르지 않습니다.** `sample_docs.json`의 예시 문서로 검색하고,
단어 빈도로 벡터를 흉내 내고, 첫 문장을 요약으로 씁니다. MSDF가 흐름을 어떻게 연결하는지 보여 주는 것이 목적입니다.

```text
chatbot ──order("search_result", q)──▶ 엔진
search.fetch(q) ─▶ embedding.embed ─▶ processing.refine ─▶ chatbot.on_search_result
```

## 한 프로세스로 빠르게 보기

```bash
python run_local.py "환불은 언제 되나요" "환불은 언제 되나요"
```

두 번째 질문은 같은 요청이므로 단계를 하나도 실행하지 않고 캐시에서 답합니다.

## 여러 프로세스로 실행

```bash
msdf up                  # 터미널 1 — 엔진. http://127.0.0.1:8787/ui 에서 흐름을 볼 수 있다
python search.py         # 터미널 2
python embedding.py      # 터미널 3
python processing.py     # 터미널 4
python chatbot.py        # 터미널 5 — 질문을 입력한다
```

## 파일

| 파일 | 내용 |
| --- | --- |
| `chatbot.py` | order를 내고 결과를 받는 서비스. `@context`로 계정 등급을 준다 |
| `search.py`, `embedding.py`, `processing.py` | 각자 Action 하나씩 |
| `dags/search_result.yaml` | 네 서비스를 잇는 DAG |
| `iam.yaml` | 계정 등급별 권한 |
| `resolvers.yaml` | 검색 결과는 SQLite, 나머지는 파일에 저장 |
| `sample_docs.json` | 예시 문서 |
