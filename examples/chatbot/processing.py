"""가공 서비스. 문서들에서 요약 한 줄과 키워드를 뽑는다."""

from collections import Counter

from ms_dataflow import action, service, start


@service("processing")
def processing(): ...


@action(inputs=["vectors"], outputs=["summary", "keywords"])
def refine(vectors: list) -> tuple[str, list]:  # 반환 순서 = outputs 순서
    if not vectors:
        return "관련 문서를 찾지 못했습니다.", []
    total: Counter = Counter()
    for d in vectors:
        total.update(d["vector"])
    keywords = [w for w, _ in total.most_common(5)]
    first = vectors[0]
    summary = f"{first['title']}: {first['body'].split('. ')[0].rstrip('.')}."
    return summary, keywords


if __name__ == "__main__":
    start(block=True)  # Ctrl+C로 종료할 때까지 Action을 처리한다
