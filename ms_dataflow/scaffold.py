"""msdf init: 바로 실행해 볼 수 있는 새 프로젝트 뼈대.

시작하기 문서의 예시와 같은 세 서비스(source → transform → app)를 만든다.
"""

from __future__ import annotations

from pathlib import Path

FILES: dict[str, str] = {
    "source.py": '''\
"""하루치 데이터를 읽는 서비스."""

from ms_dataflow import action, service, start

service("source")


@action(params=["day"], outputs=["rows"], fresh_for="1h")
def load(day: str) -> list:
    # 실제로는 DB나 외부 API에서 읽는다
    return [{"day": day, "value": v} for v in (3, None, 7, 5)]


if __name__ == "__main__":
    start(block=True)
''',
    "transform.py": '''\
"""데이터를 다듬고 집계하는 서비스."""

from ms_dataflow import action, service, start

service("transform")


@action(inputs=["rows"], outputs=["clean"], retries=2)
def clean(rows: list) -> list:
    return [r for r in rows if r["value"] is not None]


@action(inputs=["rows"], outputs=["stats"])
def summarize(rows: list) -> dict:
    values = [r["value"] for r in rows]
    return {"count": len(values), "total": sum(values)}


if __name__ == "__main__":
    start(block=True)
''',
    "app.py": '''\
"""결과를 요청하고 받는 서비스."""

import sys
import time

from ms_dataflow import action, order, service, start


@service("app")
def app(day: str) -> str:
    return order("daily_stats", params={"day": day})  # 바로 반환한다


@action(inputs=["stats"])
def on_stats(stats: dict) -> None:
    print("결과:", stats)


@action
def on_stats_failed(status: str) -> None:  # "failed" 또는 "cancelled"
    print("실패:", status)


if __name__ == "__main__":
    start()
    app(sys.argv[1] if len(sys.argv) > 1 else "2026-11-12")
    time.sleep(3)  # 실제 서비스라면 자기 서버(app.run() 등)를 계속 돌린다
''',
    "dags/daily_stats.yaml": """\
order: daily_stats

nodes:
  load:      {service: source,    action: load}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}

edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}

result: summarize.stats

deliveries:
  - requester: app
    on_success: app.on_stats
    on_fail:    app.on_stats_failed
""",
    "iam.yaml": """\
# 이 파일이 있으면 기본은 거부이고, 아래 규칙에 맞는 것만 통과한다.
# 웹 UI의 "권한" 화면에서도 고칠 수 있다.
rules:
  - {type: order, service: app}
  - {type: flow, from: source.load,         to: transform.clean}
  - {type: flow, from: transform.clean,     to: transform.summarize}
  - {type: flow, from: transform.summarize, to: app.on_stats}
""",
    ".gitignore": ".msdf/\n__pycache__/\n",
}


def init(target: Path) -> list[Path]:
    """뼈대 파일을 쓴다. 이미 있는 파일이 하나라도 있으면 아무것도 쓰지 않는다."""
    existing = [target / name for name in FILES if (target / name).exists()]
    if existing:
        raise FileExistsError(", ".join(str(p) for p in existing))
    written = []
    for name, text in FILES.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
        written.append(path)
    return written
