# 챗봇 예제

설계 문서와 구현 문서에 나오는 네 서비스(chatbot, search, embedding, processing) 예제입니다.
구현 전이므로 아직 실행되지 않습니다.

```bash
msdf up                  # 터미널 1 — 엔진
python chatbot.py        # 터미널 2 — 각 서비스
python search.py         # 터미널 3
python embedding.py      # 터미널 4
python processing.py     # 터미널 5
```

흐름: 챗봇이 `search_result`를 order → 검색 fetch → 임베딩 → 가공 → 챗봇의 `on_search_result`로 배달.
