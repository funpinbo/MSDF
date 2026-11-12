"""파일 하나를 ast로 읽어 @service, @action, order() 호출, import를 뽑는다.

코드를 실행하지 않는다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from ms_dataflow.decorators import check_signature
from ms_dataflow.errors import DeclarationError
from ms_dataflow.ids import version_of_node
from ms_dataflow.models import parse_duration

_DECORATORS = {"service", "action", "context"}
_ACTION_KW = {
    "inputs",
    "outputs",
    "params",
    "version",
    "retries",
    "retry_delay",
    "fresh_for",
}


@dataclass
class ImportRef:
    module: str  # 절대 이름. 상대 import는 level로 표시
    level: int
    names: tuple[str, ...]  # from X import a, b 의 a, b
    lineno: int


@dataclass
class ActionDecl:
    name: str
    lineno: int
    source: str
    options: dict[str, Any]
    args: tuple[str, ...]
    is_async: bool
    version: str


@dataclass
class ServiceDecl:
    name: str
    func: str
    lineno: int


@dataclass
class FileFacts:
    path: str
    services: list[ServiceDecl] = field(default_factory=list)
    actions: list[ActionDecl] = field(default_factory=list)
    orders: list[tuple[str, int]] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    has_context: bool = False
    errors: list[DeclarationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _decl_source(lines: list[str], node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    start = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
    return "\n".join(lines[start : node.lineno])


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


class _Scanner(ast.NodeVisitor):
    def __init__(self, facts: FileFacts, lines: list[str]) -> None:
        self.f = facts
        self.lines = lines
        self.alias: dict[str, str] = {}  # 로컬 이름 → service/action/context/order
        self.module_alias: set[str] = set()  # import ms_dataflow as md
        self.depth = 0

    # --- import ----------------------------------------------------------
    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            for n in node.orelse:
                self.visit(n)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            if a.name == "ms_dataflow":
                self.module_alias.add(a.asname or a.name)
            if a.name.split(".")[0] == "ms_dataflow":
                continue
            self.f.imports.append(ImportRef(a.name, 0, (), node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        names = tuple(a.name for a in node.names)
        if mod == "ms_dataflow" and node.level == 0:
            for a in node.names:
                if a.name in _DECORATORS | {"order"}:
                    self.alias[a.asname or a.name] = a.name
            return
        if mod.startswith("ms_dataflow"):
            return
        self.f.imports.append(ImportRef(mod, node.level, names, node.lineno))

    # --- 이름 판정 --------------------------------------------------------
    def _role(self, expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Call):
            expr = expr.func
        if isinstance(expr, ast.Name):
            return self.alias.get(expr.id)
        if (
            isinstance(expr, ast.Attribute)
            and isinstance(expr.value, ast.Name)
            and expr.value.id in self.module_alias
            and expr.attr in _DECORATORS | {"order"}
        ):
            return expr.attr
        return None

    # --- order() 호출과 동적 import ----------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        if (
            self._role(node.func) == "order"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            self.f.orders.append((node.args[0].value, node.lineno))
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else ""
        )
        if name in {"import_module", "__import__"}:
            self.f.warnings.append(
                f"{self.f.path}:{node.lineno}: 동적 import는 따라가지 않습니다. "
                "Action이 그 모듈에 있다면 서비스 파일에서 직접 import하세요."
            )
        self.generic_visit(node)

    # --- 함수 정의 --------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for deco in node.decorator_list:
            role = self._role(deco)
            if role == "service":
                self._service(node, deco)
            elif role == "action":
                self._action(node, deco)
            elif role == "context":
                self.f.has_context = True
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def _err(self, node: ast.FunctionDef | ast.AsyncFunctionDef, reason: str, fix: str) -> None:
        self.f.errors.append(
            DeclarationError(
                reason,
                file=self.f.path,
                line=node.lineno,
                source=_decl_source(self.lines, node),
                fix=fix,
            )
        )

    def _service(self, node: ast.FunctionDef | ast.AsyncFunctionDef, deco: ast.expr) -> None:
        if (
            not isinstance(deco, ast.Call)
            or len(deco.args) != 1
            or not isinstance(deco.args[0], ast.Constant)
            or not isinstance(deco.args[0].value, str)
        ):
            self._err(
                node, "@service에는 서비스 이름 문자열 하나를 줘야 합니다.", '@service("이름")'
            )
            return
        if self.depth:
            self._err(
                node, "@service는 모듈 최상위 함수에만 붙일 수 있습니다.", "함수를 밖으로 빼세요."
            )
            return
        self.f.services.append(ServiceDecl(deco.args[0].value, node.name, node.lineno))

    def _action(self, node: ast.FunctionDef | ast.AsyncFunctionDef, deco: ast.expr) -> None:
        source = _decl_source(self.lines, node)
        if self.depth:
            self._err(
                node, "@action은 모듈 최상위 함수에만 붙일 수 있습니다.", "함수를 밖으로 빼세요."
            )
            return
        opts: dict[str, Any] = {}
        if isinstance(deco, ast.Call):
            if deco.args:
                self._err(node, "@action의 옵션은 이름=값으로만 줍니다.", "@action(inputs=[...])")
                return
            for kw in deco.keywords:
                if kw.arg not in _ACTION_KW:
                    self._err(
                        node,
                        f"@action에 모르는 옵션 '{kw.arg}'가 있습니다.",
                        "쓸 수 있는 옵션: " + ", ".join(sorted(_ACTION_KW)),
                    )
                    return
                try:
                    opts[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    self._err(
                        node,
                        f"@action의 '{kw.arg}' 값은 리터럴이어야 합니다 (변수나 계산식 불가).",
                        f'{kw.arg}=["이름"]처럼 값을 직접 적으세요.',
                    )
                    return
        a = node.args
        args = tuple(x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs])
        inputs = tuple(opts.get("inputs", ()))
        outputs = tuple(opts.get("outputs", ("out",)))
        params = tuple(opts.get("params", ()))
        errs = check_signature(
            node.name, args, inputs, params, file=self.f.path, line=node.lineno, source=source
        )
        self.f.errors.extend(errs)
        if not outputs:
            self._err(node, "outputs가 비어 있습니다.", 'outputs=["out"]처럼 하나 이상 선언하세요.')
        try:
            opts["fresh_for"] = parse_duration(opts.get("fresh_for"))
        except ValueError as e:
            self._err(node, str(e), 'fresh_for="1d"처럼 적으세요.')
        if (
            len(outputs) > 1
            and node.returns is not None
            and "tuple" not in ast.unparse(node.returns).lower()
        ):
            self.f.warnings.append(
                f"{self.f.path}:{node.lineno}: outputs가 {len(outputs)}개인데 "
                "반환 타입이 tuple이 아닙니다."
            )
        version = opts.get("version") or version_of_node(node)
        self.f.actions.append(
            ActionDecl(
                name=node.name,
                lineno=node.lineno,
                source=source,
                options={**opts, "inputs": inputs, "outputs": outputs, "params": params},
                args=args,
                is_async=isinstance(node, ast.AsyncFunctionDef),
                version=str(version),
            )
        )


def scan_source(path: str, text: str) -> FileFacts:
    facts = FileFacts(path=path)
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as e:
        facts.errors.append(
            DeclarationError(
                f"문법 오류: {e.msg}", file=path, line=e.lineno, fix="파이썬 문법을 확인하세요."
            )
        )
        return facts
    _Scanner(facts, text.splitlines()).visit(tree)
    return facts
