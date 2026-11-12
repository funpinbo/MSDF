"""msdf CLI.

- ``msdf up``: 설정을 읽고 검증한 뒤 엔진(Scheduler + DB + 웹 UI)을 띄운다. 서비스는 띄우지 않는다.
- ``msdf check``: 설정과 코드만 검증하고 끝낸다.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ms_dataflow import __version__
from ms_dataflow.errors import LoadError
from ms_dataflow.models import Settings
from ms_dataflow.project import Project, load_project


def _load(args: argparse.Namespace) -> Project | None:
    try:
        project = load_project(
            args.root, config_dir=args.config, strict_services=not args.allow_external
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


def build_app(project: Project, db: str, settings: Settings, *, ui: bool = True) -> object:
    from ms_dataflow.execute.scheduler import Scheduler
    from ms_dataflow.store import Store

    sched = Scheduler(project, Store(db), settings)
    if ui:
        from ms_dataflow.ui import install as install_ui

        install_ui(sched)
    return sched.app()


def cmd_up(args: argparse.Namespace) -> int:
    project = _load(args)
    if project is None:
        return 1
    import uvicorn

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
    try:
        app = build_app(project, db, settings, ui=not args.no_ui)
    except LoadError as e:
        print(e.render(), file=sys.stderr)
        return 1
    print(f"MSDF {__version__}: {_summary(project)}")
    print(f"엔진: http://{args.host}:{args.port}  (UI: http://{args.host}:{args.port}/ui)")
    if not args.no_ui:
        from ms_dataflow.ui import dist_dir

        if not (dist_dir() / "index.html").exists():
            print(f"UI 빌드 없음 ({dist_dir()}): /ui에서 빌드 방법을 안내합니다.")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("주의: 엔진 API에는 인증이 없습니다. 믿을 수 있는 네트워크에서만 여세요.")
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
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")  # type: ignore[arg-type]
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = _load(args)
    if project is None:
        return 1
    print(f"문제 없음: {_summary(project)}")
    return 0


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
    up.set_defaults(func=cmd_up)

    check = sub.add_parser("check", help="설정과 코드를 검증만 한다")
    common(check)
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
