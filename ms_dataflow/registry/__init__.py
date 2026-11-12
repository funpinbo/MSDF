"""레지스트리: ast 분석으로 서비스와 Action을 수집하고 소속을 판정한다."""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ms_dataflow.errors import DeclarationError, LoadError, raise_collected
from ms_dataflow.models import ActionSpec, ServiceSpec
from ms_dataflow.registry.scan import FileFacts, ImportRef, scan_source

_SKIP_DIRS = {
    "__pycache__",
    "venv",
    "env",
    "site-packages",
    "node_modules",
    "build",
    "dist",
}


@dataclass
class Registry:
    """로딩이 끝나면 읽기 전용으로 쓴다."""

    root: str
    services: dict[str, ServiceSpec] = field(default_factory=dict)
    actions: dict[tuple[str, str], ActionSpec] = field(default_factory=dict)
    file_owner: dict[str, str | None] = field(default_factory=dict)  # None = 여러 서비스 공유
    context_files: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def action(self, service: str, name: str) -> ActionSpec | None:
        return self.actions.get((service, name))

    def owner_of(self, file: str) -> str | None:
        return self.file_owner.get(os.path.realpath(file))

    def merge(self, other: Registry) -> None:
        """다른 프로세스가 등록한 명세로 덮어쓴다 (실제 실행 중인 코드가 기준)."""
        self.services.update(other.services)
        for key, spec in other.actions.items():
            self.actions[key] = spec


def _py_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
        out += [Path(dirpath, f) for f in filenames if f.endswith(".py")]
    return sorted(out)


def _module_candidates(root: Path, file: Path, ref: ImportRef) -> list[Path]:
    """import 하나가 가리킬 수 있는 프로젝트 안 파일 후보."""
    names: list[str] = []
    if ref.level:
        base = file.parent
        for _ in range(ref.level - 1):
            base = base.parent
        parts = ref.module.split(".") if ref.module else []
        bases = [base.joinpath(*parts)] if parts else [base]
        for b in list(bases):
            for n in ref.names:
                bases.insert(0, b / n)
        cands: list[Path] = []
        for b in bases:
            cands += [b.with_suffix(".py"), b / "__init__.py"]
        return cands
    names.append(ref.module)
    names = [f"{ref.module}.{n}" for n in ref.names] + names
    cands = []
    for name in names:
        parts = name.split(".")
        for base in (root, file.parent):
            p = base.joinpath(*parts)
            cands += [p.with_suffix(".py"), p / "__init__.py"]
    return cands


def collect(
    root: str | Path,
    *,
    entry: str | Path | None = None,
    files: list[Path] | None = None,
) -> Registry:
    """프로젝트를 분석한다.

    ``entry``를 주면 그 파일에서 import로 닿는 곳에 있는 서비스만 모은다(start()가 쓴다).
    오류가 있으면 모아서 LoadError(또는 LoadErrors)로 던진다.
    """
    rootp = Path(root).resolve()
    all_files = [p.resolve() for p in (files or _py_files(rootp))]
    if entry is not None:
        e = Path(entry).resolve()
        if e not in all_files:
            all_files.append(e)
    facts: dict[Path, FileFacts] = {}
    for p in all_files:
        try:
            text = p.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        facts[p] = scan_source(str(p), text)

    reg = Registry(root=str(rootp))
    errors: list[LoadError] = []
    for f in facts.values():
        errors += f.errors
        reg.warnings += f.warnings
        if f.has_context:
            reg.context_files.add(f.path)

    edges: dict[Path, list[Path]] = {}
    for p, f in facts.items():
        targets: list[Path] = []
        for ref in f.imports:
            for c in _module_candidates(rootp, p, ref):
                c = c.resolve()
                if c in facts and c != p:
                    targets.append(c)
                    break
        edges[p] = targets

    def reach(start: Path) -> dict[Path, Path | None]:
        seen: dict[Path, Path | None] = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            for nxt in edges.get(cur, []):
                if nxt not in seen:
                    seen[nxt] = cur
                    q.append(nxt)
        return seen

    def chain(parents: dict[Path, Path | None], end: Path) -> str:
        out = []
        cur: Path | None = end
        while cur is not None:
            out.append(cur.name)
            cur = parents[cur]
        return " → ".join(reversed(out))

    entries = [p for p, f in facts.items() if f.services]
    if entry is not None:
        allowed = set(reach(Path(entry).resolve()))
        entries = [p for p in entries if p in allowed]

    claimed: dict[tuple[Path, str], tuple[str, str]] = {}
    for p in entries:
        for sd in facts[p].services:
            if sd.name in reg.services:
                other = reg.services[sd.name]
                errors.append(
                    DeclarationError(
                        f"서비스 이름 '{sd.name}'이 두 번 선언되었습니다 "
                        f"(다른 곳: {other.file}:{other.lineno}).",
                        file=str(p),
                        line=sd.lineno,
                        fix="서비스 이름을 하나로 정하세요.",
                    )
                )
                continue
            parents = reach(p)
            action_names: list[str] = []
            orders: list[str] = []
            for fp in parents:
                ff = facts[fp]
                orders += [o for o, _ in ff.orders]
                owner = reg.file_owner.get(str(fp), sd.name)
                reg.file_owner[str(fp)] = sd.name if owner == sd.name else None
                for ad in ff.actions:
                    key = (fp, ad.name)
                    if key in claimed and claimed[key][0] != sd.name:
                        other_svc, other_chain = claimed[key]
                        errors.append(
                            DeclarationError(
                                f"Action '{ad.name}'에 두 서비스가 닿습니다: "
                                f"'{other_svc}' ({other_chain}), "
                                f"'{sd.name}' ({chain(parents, fp)}).",
                                file=str(fp),
                                line=ad.lineno,
                                source=ad.source,
                                fix="공통 로직은 @action이 없는 일반 함수로 두고, "
                                "서비스마다 자기 Action에서 그 함수를 호출하세요.",
                            )
                        )
                        continue
                    claimed[key] = (sd.name, chain(parents, fp))
                    if (sd.name, ad.name) in reg.actions:
                        prev = reg.actions[(sd.name, ad.name)]
                        errors.append(
                            DeclarationError(
                                f"서비스 '{sd.name}'에 Action '{ad.name}'이 두 개 있습니다 "
                                f"(다른 곳: {prev.file}:{prev.lineno}).",
                                file=str(fp),
                                line=ad.lineno,
                                source=ad.source,
                                fix="한 서비스 안에서 Action 이름이 겹치지 않게 하세요.",
                            )
                        )
                        continue
                    o = ad.options
                    reg.actions[(sd.name, ad.name)] = ActionSpec(
                        service=sd.name,
                        name=ad.name,
                        inputs=o["inputs"],
                        outputs=o["outputs"],
                        params=o["params"],
                        version=ad.version,
                        retries=int(o.get("retries", 0)),
                        retry_delay=float(o.get("retry_delay", 0.0)),
                        fresh_for=o.get("fresh_for"),
                        file=str(fp),
                        lineno=ad.lineno,
                        args=ad.args,
                        is_async=ad.is_async,
                    )
                    action_names.append(ad.name)
            reg.services[sd.name] = ServiceSpec(
                name=sd.name,
                file=str(p),
                lineno=sd.lineno,
                actions=tuple(action_names),
                orders=tuple(sorted(set(orders))),
                files=tuple(sorted(str(x) for x in parents)),
            )

    if entry is None:
        claimed_files = {fp for fp, _ in claimed}
        for p, f in facts.items():
            if f.actions and p not in claimed_files:
                reg.warnings.append(
                    f"{p}: Action {', '.join(a.name for a in f.actions)}이(가) "
                    "어느 @service에서도 import로 닿지 않습니다."
                )
    raise_collected(errors)
    return reg
