"""검색 서비스. 실제 검색 엔진 대신 sample_docs.json에서 단어가 겹치는 문서를 찾는다."""

import json
import os
import re

from ms_dataflow import action, service, start

DOCS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_docs.json")


def words(text: str) -> set[str]:
    return set(re.findall(r"[0-9A-Za-z가-힣]+", text.lower()))


@service("search")
def search(): ...


@action(params=["q"], outputs=["out"], fresh_for="1d", retries=3)
def fetch(q: str) -> list:
    with open(DOCS_FILE, encoding="utf-8") as f:
        docs = json.load(f)
    query = words(q)
    hits = [d for d in docs if query & words(d["title"] + " " + d["body"])]
    return hits[:5]


if __name__ == "__main__":
    start(block=True)  # Ctrl+C로 종료할 때까지 Action을 처리한다
