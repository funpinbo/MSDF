"""사용자가 쓰는 데코레이터와 order().

소속 판정과 슬롯 수집은 ast 분석(registry)이 맡는다. 여기서는 실행할 때 함수를 찾을 수 있게
등록하고, 선언이 함수 시그니처와 맞는지만 바로 확인한다.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import threading
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any, Protocol, TypeVar, overload

from ms_dataflow.errors import DeclarationError, OrderError
from ms_dataflow.models import parse_duration

F = TypeVar("F", bound=Callable[..., Any])

_lock = threading.Lock()
_FUNCTIONS: dict[tuple[str, str], Callable[..., Any]] = {}
_CONTEXT: list[Callable[[], dict[str, Any]]] = []


def _realpath(path: str) -> str:
    return os.path.realpath(path)


def _where(fn: Callable[..., Any]) -> tuple[str, int]:
    code = getattr(fn, "__code__", None)
    if code is None:
        return "<unknown>", 0
    return _realpath(code.co_filename), code.co_firstlineno


def _remember(fn: Callable[..., Any]) -> None:
    file, _ = _where(fn)
    with _lock:
        _FUNCTIONS[(file, fn.__name__)] = fn


# --- @service --------------------------------------------------------------
def service(name: str) -> Callable[[F], F]:
    """서비스의 진입점을 표시한다. 이 함수의 파일에서 import로 닿는 Action이 이 서비스 것이다."""
    if not isinstance(name, str) or not name.isidentifier():
        raise DeclarationError(
            f"서비스 이름은 파이썬 식별자 형식의 문자열이어야 합니다: {name!r}",
            fix='@service("billing")처럼 영문, 숫자, 밑줄로 지으세요.',
        )

    def deco(fn: F) -> F:
        fn.__msdf_service__ = name  # type: ignore[attr-defined]
        _remember(fn)
        return fn

    return deco


# --- @action ---------------------------------------------------------------
def check_signature(
    fn_name: str,
    args: Sequence[str],
    inputs: Sequence[str],
    params: Sequence[str],
    *,
    file: str | None,
    line: int | None,
    source: str | None,
) -> list[DeclarationError]:
    """선언한 inputs/params가 함수 인자와 맞는지. ast 분석과 런타임이 같은 규칙을 쓴다."""
    errors: list[DeclarationError] = []
    declared = list(inputs) + list(params)
    for dup in {n for n in declared if declared.count(n) > 1}:
        errors.append(
            DeclarationError(
                f"슬롯/파라미터 이름 '{dup}'가 두 번 선언되었습니다.",
                file=file,
                line=line,
                source=source,
                fix="inputs와 params에서 이름이 겹치지 않게 하세요.",
            )
        )
    for n in declared:
        if n not in args:
            kind = "입력 슬롯" if n in inputs else "파라미터"
            errors.append(
                DeclarationError(
                    f"선언한 {kind} '{n}'가 함수 인자에 없습니다.\n  함수 인자: "
                    + (", ".join(args) or "(없음)"),
                    file=file,
                    line=line,
                    source=source,
                    fix=f"{fn_name}의 인자 이름을 '{n}'로 맞추거나 선언을 고치세요.",
                )
            )
    return errors


@overload
def action(func: F) -> F: ...
@overload
def action(
    func: None = None,
    *,
    inputs: Sequence[str] = (),
    outputs: Sequence[str] = ("out",),
    params: Sequence[str] = (),
    version: str | None = None,
    retries: int = 0,
    retry_delay: float = 0.0,
    fresh_for: str | float | None = None,
) -> Callable[[F], F]: ...


def action(
    func: Callable[..., Any] | None = None,
    *,
    inputs: Sequence[str] = (),
    outputs: Sequence[str] = ("out",),
    params: Sequence[str] = (),
    version: str | None = None,
    retries: int = 0,
    retry_delay: float = 0.0,
    fresh_for: str | float | None = None,
) -> Any:
    """데이터를 읽거나 쓰는 지점을 표시한다. ``@action``과 ``@action(...)`` 둘 다 된다."""

    def deco(fn: F) -> F:
        file, line = _where(fn)
        try:
            args = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):  # pragma: no cover - 내장 함수 등
            args = []
        errs = check_signature(fn.__name__, args, inputs, params, file=file, line=line, source=None)
        if errs:
            raise errs[0]
        if retries < 0:
            raise DeclarationError("retries는 0 이상이어야 합니다.", file=file, line=line)
        try:
            parse_duration(fresh_for)
        except ValueError as e:
            raise DeclarationError(str(e), file=file, line=line) from None
        fn.__msdf_action__ = {  # type: ignore[attr-defined]
            "inputs": tuple(inputs),
            "outputs": tuple(outputs),
            "params": tuple(params),
            "version": version,
            "retries": retries,
            "retry_delay": retry_delay,
            "fresh_for": fresh_for,
        }
        _remember(fn)
        return fn

    if func is not None:
        return deco(func)
    return deco


# --- @context --------------------------------------------------------------
def context(fn: Callable[[], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
    """권한 검사에 쓸 계층 값(계정 등)을 돌려주는 함수를 표시한다. order마다 호출된다."""
    with _lock:
        _CONTEXT.clear()
        _CONTEXT.append(fn)
    return fn


def current_context() -> dict[str, str]:
    if not _CONTEXT:
        return {}
    value = _CONTEXT[0]()
    if not isinstance(value, dict):
        raise OrderError("@context 함수는 dict를 돌려줘야 합니다")
    return {str(k): str(v) for k, v in value.items()}


def context_declared() -> bool:
    return bool(_CONTEXT)


# --- order() ---------------------------------------------------------------
class OrderBackend(Protocol):
    def submit(self, name: str, params: dict[str, Any], caller_file: str) -> str: ...


_BACKEND: list[OrderBackend] = []


def set_backend(backend: OrderBackend | None) -> None:
    with _lock:
        _BACKEND.clear()
        if backend is not None:
            _BACKEND.append(backend)


def order(name: str, params: dict[str, Any] | None = None) -> str:
    """결과물을 이름으로 요청한다. 즉시 반환하며, 결과는 DAG의 deliveries로 도착한다.

    반환값은 요청의 정체(lineage_key)다. 요청 서비스 이름은 자동으로 채워진다.
    """
    if not _BACKEND:
        raise OrderError("엔진에 연결되지 않았습니다. 서비스 시작 시 start()를 먼저 호출하세요.")
    caller = _realpath(sys._getframe(1).f_code.co_filename)
    return _BACKEND[0].submit(name, dict(params or {}), caller)


# --- 실행 시점에 함수 찾기 ---------------------------------------------------
_loaded: dict[str, ModuleType] = {}


def _module_for(file: str, roots: Sequence[str]) -> ModuleType:
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if f and _realpath(f) == file:
            return mod
    if file in _loaded:
        return _loaded[file]
    for p in [os.path.dirname(file), *roots]:
        if p not in sys.path:
            sys.path.insert(0, p)
    name = "msdf_user_" + str(abs(hash(file)))
    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _loaded[file] = mod
    return mod


def resolve_function(file: str, name: str, roots: Sequence[str] = ()) -> Callable[..., Any]:
    """Action 함수를 찾는다. 이미 import된 것을 먼저 쓰고, 없으면 그 파일만 import한다."""
    key = (_realpath(file), name)
    with _lock:
        fn = _FUNCTIONS.get(key)
    if fn is not None:
        return fn
    _module_for(key[0], roots)
    with _lock:
        fn = _FUNCTIONS.get(key)
    if fn is None:
        raise LookupError(f"{file}에서 Action '{name}'을 찾지 못했습니다")
    return fn
