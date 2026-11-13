"""레지스트리: ast 분석으로 서비스와 Action을 수집하고 소속을 판정한다."""

from __future__ import annotations

import hashlib
import os
import pickle
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ms_dataflow.errors import DeclarationError, LoadError, raise_collected
from ms_dataflow.models import ActionSpec, ServiceSpec
from ms_dataflow.registry.scan import FileFacts, ImportRef, TopDef, scan_source

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


def _module_file(root: Path, file: Path, ref: ImportRef, known: set[Path]) -> Path | None:
    """import가 가리키는 모듈 파일 (프로젝트 안에 있을 때만)."""
    parts = ref.module.split(".") if ref.module else []
    if ref.level:
        base = file.parent
        for _ in range(ref.level - 1):
            base = base.parent
        bases = [base.joinpath(*parts)]
    else:
        bases = [root.joinpath(*parts), file.parent.joinpath(*parts)]
    for b in bases:
        for c in (b.with_suffix(".py"), b / "__init__.py"):
            c = c.resolve()
            if c in known:
                return c
    return None


def helper_version(
    root: Path, facts: dict[Path, FileFacts], file: Path, action: str, body_version: str
) -> str:
    """Action 본문에 더해, 본문이 부르는 프로젝트 안 함수·클래스·상수까지 반영한 버전.

    도우미 코드가 없으면 본문 버전을 그대로 쓴다 (0.1과 같은 값).
    """
    known = set(facts)
    start = facts[file].action_refs.get(action)
    if start is None:
        return body_version

    def lookup(f: Path, name: str) -> tuple[Path, str] | None:
        ff = facts[f]
        if name in ff.defs:
            return f, name
        imp = ff.import_names.get(name)
        if imp is None or imp[1] is None:
            return None
        ref, orig = imp
        mod = _module_file(root, f, ref, known)
        if mod is not None and orig in facts[mod].defs:
            return mod, orig
        return None

    def module_alias(f: Path, name: str) -> Path | None:
        imp = facts[f].import_names.get(name)
        if imp is None:
            return None
        ref, orig = imp
        if orig is None:
            return _module_file(root, f, ref, known)
        sub = ImportRef(f"{ref.module}.{orig}" if ref.module else orig, ref.level, (), ref.lineno)
        return _module_file(root, f, sub, known)

    seen: set[tuple[Path, str]] = {(file, action)}
    found: list[str] = []
    stack: list[tuple[Path, TopDef]] = [(file, start)]
    while stack:
        f, top = stack.pop()
        targets = [lookup(f, n) for n in sorted(top.names)]
        for mod_name, attr in sorted(top.attrs):
            mod = module_alias(f, mod_name)
            if mod is not None and attr in facts[mod].defs:
                targets.append((mod, attr))
        for t in targets:
            if t is None or t in seen:
                continue
            seen.add(t)
            d = facts[t[0]].defs[t[1]]
            found.append(f"{t[1]}:{d.digest}")
            stack.append((t[0], d))
    if not found:
        return body_version
    h = hashlib.sha256(body_version.encode())
    for item in sorted(found):
        h.update(b"\x1f" + item.encode())
    return h.hexdigest()[:12]


class ScanCache:
    """파일별 분석 결과 캐시.

    (경로, 수정 시각, 크기, MSDF·파이썬 버전)이 같으면 다시 분석하지 않는다.

    오류가 있는 파일은 캐시하지 않는다(다음에 다시 분석해 같은 오류를 보여 준다).
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.items: dict[str, tuple[tuple[int, int], FileFacts]] = {}
        self.dirty = False
        if path is not None and path.exists():
            try:
                with path.open("rb") as f:
                    data = pickle.load(f)
                if data.get("key") == self._key():
                    self.items = data["items"]
            except Exception:  # noqa: BLE001 - 깨진 캐시는 버린다
                self.items = {}

    @staticmethod
    def _key() -> str:
        from ms_dataflow import __version__

        return f"{__version__}|{sys.version_info[:2]}"

    def get(self, p: Path) -> FileFacts:
        st = p.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        hit = self.items.get(str(p))
        if hit is not None and hit[0] == stamp:
            return hit[1]
        facts = scan_source(str(p), p.read_text("utf-8"))
        if not facts.errors:
            self.items[str(p)] = (stamp, facts)
            self.dirty = True
        return facts

    def save(self) -> None:
        if self.path is None or not self.dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            with tmp.open("wb") as f:
                pickle.dump({"key": self._key(), "items": self.items}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass


def collect(
    root: str | Path,
    *,
    entry: str | Path | None = None,
    files: list[Path] | None = None,
    cache: Path | None = None,
) -> Registry:
    """프로젝트를 분석한다.

    ``entry``를 주면 그 파일에서 import로 닿는 곳에 있는 서비스만 모은다(start()가 쓴다).
    ``cache``를 주면 그 파일에 분석 결과를 저장해 두고, 바뀌지 않은 파일은 다시 분석하지 않는다.
    오류가 있으면 모아서 LoadError(또는 LoadErrors)로 던진다.
    """
    rootp = Path(root).resolve()
    all_files = [p.resolve() for p in (files or _py_files(rootp))]
    if entry is not None:
        e = Path(entry).resolve()
        if e not in all_files:
            all_files.append(e)
    facts: dict[Path, FileFacts] = {}
    sc = ScanCache(cache)
    for p in all_files:
        try:
            facts[p] = sc.get(p)
        except (OSError, UnicodeDecodeError):
            continue
    sc.save()

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
                        version=ad.version
                        if ad.explicit_version
                        else helper_version(rootp, facts, fp, ad.name, ad.version),
                        retries=int(o.get("retries", 0)),
                        retry_delay=float(o.get("retry_delay", 0.0)),
                        fresh_for=o.get("fresh_for"),
                        file=str(fp),
                        lineno=ad.lineno,
                        args=ad.args,
                        is_async=ad.is_async,
                        arg_types=dict(getattr(ad, "arg_types", {})),
                        returns=getattr(ad, "returns", None),
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
