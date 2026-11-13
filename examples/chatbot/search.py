"""검색 서비스. 실제 검색 엔진 대신 sample_docs.json에서 단어가 겹치는 문서를 찾는다."""

import json
import os
import re
import threading
import time

from ms_dataflow import action, invalidate, service, start

DOCS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_docs.json")


def words(text: str) -> set[str]:
    return set(re.findall(r"[0-9A-Za-z가-힣]+", text.lower()))


service("search")


@action(params=["q"], outputs=["out"], fresh_for="1d", retries=3)
def fetch(q: str) -> list:
    with open(DOCS_FILE, encoding="utf-8") as f:
        docs = json.load(f)
    query = words(q)
    hits = [d for d in docs if query & words(d["title"] + " " + d["body"])]
    return hits[:5]


def watch_docs(every: float = 2.0) -> None:
    """문서 파일이 바뀌면 엔진에 알린다.

    누가 이 데이터에 기대는지는 모른다. 엔진이 계보로 찾아 fetch부터 다시 계산하고,
    이 데이터에 기대는 구독(열려 있는 대화)에 새 답을 보낸다.
    """
    last = os.stat(DOCS_FILE).st_mtime_ns
    while True:
        time.sleep(every)
        now = os.stat(DOCS_FILE).st_mtime_ns
        if now != last:
            last = now
            invalidate("fetch", data_version=str(now))
            print("[검색] 문서가 바뀌어 엔진에 알렸습니다", flush=True)


if __name__ == "__main__":
    start()
    threading.Thread(target=watch_docs, daemon=True, name="watch-docs").start()
    start(block=True)  # Ctrl+C로 종료할 때까지 Action을 처리한다
