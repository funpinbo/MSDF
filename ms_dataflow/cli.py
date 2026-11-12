"""msdf CLI.

- ``msdf up``: 설정을 읽고 검증한 뒤 엔진(Scheduler + DB + 웹 UI)을 띄운다. 서비스는 띄우지 않는다.
- ``msdf check``: 설정과 코드만 검증하고 끝낸다.
- ``msdf init``: 새 프로젝트 뼈대를 만든다.
- ``msdf status`` / ``msdf runs`` / ``msdf cancel``: 떠 있는 엔진에 묻는다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ms_dataflow import __version__
from ms_dataflow.errors import LoadError
from ms_dataflow.models import Settings
from ms_dataflow.project import Project, load_project


def _load(args: argparse.Namespace) -> Project | None:
    try:
        project = load_project(
            args.root,
            config_dir=args.config,
            strict_services=not args.allow_external,
            cache=not args.no_cache,
        )
    except LoadError as e:
        print(e.render(), file=sys.stderr)
        return None
    for w in project.warnings:
        print(f"경고: {w}", file=sys.stderr)
    return project


def _summary(project: Project) -> str:
    reg = project.registry
    return (
        f"서비스 {len(reg.services)}개, Action {len(reg.actions)}개, "
        f"DAG {len(project.dags)}개 ({', '.join(sorted(project.dags)) or '없음'}), "
        f"IAM {'사용' if project.iam else '없음'}"
    )


def build_app(
    project: Project, db: str, settings: Settings, *, ui: bool = True, token: str | None = None
) -> object:
    from ms_dataflow.execute.scheduler import Scheduler
    from ms_dataflow.store import Store

    sched = Scheduler(project, Store(db), settings, token=token)
    if ui:
        from ms_dataflow.ui import install as install_ui

        install_ui(sched)
    return sched.app()


def cmd_up(args: argparse.Namespace) -> int:
    project = _load(args)
    if project is None:
        return 1
    settings = Settings(
        lease_ttl=args.lease_ttl,
        heartbeat_every=args.lease_ttl / 3,
        reaper_every=min(10.0, args.lease_ttl / 6),
        keep_generations=args.keep_generations,
        keep_versions=args.keep_versions,
    )
    db = args.db or str(Path(args.config or args.root) / ".msdf" / "msdf.db")
    if args.ui_dist:
        os.environ["MSDF_UI_DIST"] = str(Path(args.ui_dist).resolve())
    token = args.token or os.environ.get("MSDF_TOKEN") or None
    try:
        app = build_app(project, db, settings, ui=not args.no_ui, token=token)
    except ImportError as e:
        print(
            f"msdf up에는 server 묶음이 필요합니다 ({e.name or e}). "
            '"pip install msdf[server]" (저장소에서는 uv sync --all-extras)로 설치하세요.',
            file=sys.stderr,
        )
        return 1
    except LoadError as e:
        print(e.render(), file=sys.stderr)
        return 1
    print(f"MSDF {__version__}: {_summary(project)}")
    print(f"엔진: http://{args.host}:{args.port}  (UI: http://{args.host}:{args.port}/ui)")
    if not args.no_ui:
        from ms_dataflow.ui import dist_dir

        if not (dist_dir() / "index.html").exists():
            print(f"UI 빌드 없음 ({dist_dir()}): /ui에서 빌드 방법을 안내합니다.")
    if token:
        print("토큰 사용: 서비스는 MSDF_TOKEN, 웹 UI는 처음 열 때 같은 값을 입력합니다.")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        if not token:
            print(
                "주의: 토큰 없이 외부에 열었습니다. 누구나 API를 부를 수 있습니다. "
                "--token(또는 MSDF_TOKEN)을 쓰세요."
            )
    else:
        print(
            "이 주소는 엔진이 도는 컴퓨터에서만 열립니다. "
            "다른 컴퓨터(원격 서버, VM)의 브라우저에서 보려면\n"
            f"  내 컴퓨터에서: ssh -L {args.port}:127.0.0.1:{args.port} 사용자@서버  "
            f"→ http://127.0.0.1:{args.port}/ui"
        )
    print(f"DB: {db}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")  # type: ignore[arg-type]
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = _load(args)
    if project is None:
        return 1
    print(f"문제 없음: {_summary(project)}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from ms_dataflow.scaffold import init

    target = Path(args.dir)
    try:
        written = init(target)
    except FileExistsError as e:
        print(f"이미 있는 파일이 있어 아무것도 만들지 않았습니다: {e}", file=sys.stderr)
        return 1
    for p in written:
        print(f"  만듦  {p}")
    where = "" if args.dir == "." else f"cd {args.dir}\n  "
    print(
        "\n다음 순서로 실행해 보세요 (터미널 네 개):\n"
        f"  {where}msdf up\n  python source.py\n  python transform.py\n  python app.py"
    )
    return 0


# --- 떠 있는 엔진에 묻기 -------------------------------------------------------
def _engine(args: argparse.Namespace) -> tuple[str, str | None]:
    url = (args.engine or os.environ.get("MSDF_SCHEDULER") or "http://127.0.0.1:8787").rstrip("/")
    return url, args.token or os.environ.get("MSDF_TOKEN") or None


def _call(args: argparse.Namespace, method: str, path: str) -> Any:
    url, token = _engine(args)
    req = urllib.request.Request(url + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit(
                "엔진이 토큰을 요구합니다. --token 또는 MSDF_TOKEN을 주세요."
            ) from None
        if e.code == 404:
            raise SystemExit(f"없습니다: {path}") from None
        raise SystemExit(f"엔진 오류 {e.code}: {e.read().decode(errors='replace')}") from None
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"엔진({url})에 연결하지 못했습니다: {e}. msdf up이 떠 있나요?") from None


def _ago(t: float | None) -> str:
    if not t:
        return "-"
    s = max(0.0, time.time() - t)
    for unit, size in (("일", 86400), ("시간", 3600), ("분", 60)):
        if s >= size:
            return f"{int(s // size)}{unit} 전"
    return f"{int(s)}초 전"


def cmd_status(args: argparse.Namespace) -> int:
    o = _call(args, "GET", "/api/overview")
    t = o.get("totals", {})
    print(f"엔진: {_engine(args)[0]}")
    print(
        f"최근 1시간 run {t.get('runs', 0)}개: 완료 {t.get('runs_done', 0)}, "
        f"실패 {t.get('runs_failed', 0)}, 진행 중 {t.get('runs_running', 0)}"
    )
    print("서비스:")
    for svc in o.get("services", []):
        inst = svc.get("instances", [])
        busy = sum(1 for i in inst if i.get("busy"))
        state = f"인스턴스 {len(inst)}개 (실행 중 {busy})" if inst else "연결 안 됨"
        print(f"  {svc['name']:<20} {state}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    q = f"/api/runs?limit={args.limit}" + (f"&status={args.status}" if args.status else "")
    runs = _call(args, "GET", q)
    if not runs:
        print("실행 기록이 없습니다.")
        return 0
    print(f"{'run':<18}{'order':<20}{'요청':<14}{'상태':<11}시작")
    for r in runs:
        print(
            f"{r['run_id']:<18}{r['order_name']:<20}{r['requester']:<14}"
            f"{r['status']:<11}{_ago(r.get('created_at'))}"
        )
        if r.get("error") and r["status"] != "done":
            print(f"{'':<18}└ {str(r['error']).splitlines()[-1][:100]}")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    out = _call(args, "POST", f"/api/runs/{args.run_id}/cancel")
    if out.get("ok"):
        kept = f", 다른 요청과 공유해 계속 도는 단계 {out['kept']}개" if out.get("kept") else ""
        print(f"취소했습니다: 단계 {out['cancelled']}개 중지{kept}")
        return 0
    print(f"취소할 수 없습니다: 이미 {out.get('status')} 상태입니다.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="msdf", description="MSDF — Micro Service Data Flow")
    parser.add_argument("--version", action="version", version=f"msdf {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", default=".", help="서비스 코드를 찾을 프로젝트 폴더 (기본: .)")
        p.add_argument(
            "--config",
            default=None,
            help="dags/, iam.yaml, resolvers.yaml이 있는 폴더 (기본: --root)",
        )
        p.add_argument(
            "--allow-external",
            action="store_true",
            help="DAG가 참조하는 서비스가 이 프로젝트에 없어도 허용한다 (다른 저장소의 서비스). "
            "그 서비스는 등록할 때 검사한다",
        )
        p.add_argument(
            "--no-cache",
            action="store_true",
            help="코드 분석 캐시(<config>/.msdf/scan.cache)를 쓰지 않는다",
        )

    up = sub.add_parser("up", help="엔진을 띄운다")
    common(up)
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=8787)
    up.add_argument("--db", default=None, help="메타데이터 DB 경로 (기본: <config>/.msdf/msdf.db)")
    up.add_argument("--lease-ttl", type=float, default=60.0, help="단계 lease 시간(초)")
    up.add_argument("--keep-generations", type=int, default=3, help="hot에 둘 generation 수 (N)")
    up.add_argument("--keep-versions", type=int, default=3, help="hot에 둘 version 복제본 수 (M)")
    up.add_argument("--no-ui", action="store_true", help="웹 UI를 띄우지 않는다")
    up.add_argument(
        "--ui-dist",
        default=None,
        help="빌드한 웹 UI 폴더 (기본: 패키지 안 ms_dataflow/ui/dist, 환경 변수 MSDF_UI_DIST)",
    )
    up.add_argument(
        "--token",
        default=None,
        help="서비스와 웹 UI가 보내야 하는 비밀 값 (기본: 환경 변수 MSDF_TOKEN). 외부에 열 때 쓴다",
    )
    up.set_defaults(func=cmd_up)

    check = sub.add_parser("check", help="설정과 코드를 검증만 한다")
    common(check)
    check.set_defaults(func=cmd_check)

    init = sub.add_parser("init", help="새 프로젝트 뼈대를 만든다")
    init.add_argument("dir", nargs="?", default=".", help="만들 폴더 (기본: .)")
    init.set_defaults(func=cmd_init)

    def remote(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--engine", default=None, help="엔진 주소 (기본: MSDF_SCHEDULER 또는 127.0.0.1:8787)"
        )
        p.add_argument("--token", default=None, help="엔진 토큰 (기본: MSDF_TOKEN)")

    status = sub.add_parser("status", help="떠 있는 엔진과 서비스 상태를 본다")
    remote(status)
    status.set_defaults(func=cmd_status)

    runs = sub.add_parser("runs", help="최근 실행(run) 목록")
    remote(runs)
    runs.add_argument("--limit", type=int, default=20)
    runs.add_argument("--status", choices=["running", "done", "failed", "cancelled"])
    runs.set_defaults(func=cmd_runs)

    cancel = sub.add_parser("cancel", help="진행 중인 run을 취소한다")
    remote(cancel)
    cancel.add_argument("run_id")
    cancel.set_defaults(func=cmd_cancel)

    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
