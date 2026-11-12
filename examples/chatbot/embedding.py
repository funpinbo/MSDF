"""임베딩 서비스. 실제 모델 대신 단어 빈도로 만든 작은 벡터를 붙인다."""

import re
from collections import Counter

from ms_dataflow import action, service, start

service("embedding")


@action(inputs=["docs"], outputs=["out"], retries=3)
def embed(docs: list) -> list:
    out = []
    for d in docs:
        counts = Counter(re.findall(r"[0-9A-Za-z가-힣]+", d["body"].lower()))
        out.append({**d, "vector": dict(counts.most_common(8))})
    return out


if __name__ == "__main__":
    start(block=True)  # Ctrl+C로 종료할 때까지 Action을 처리한다
