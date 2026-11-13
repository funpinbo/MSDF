"""DAG 연결의 타입 검사. 코드를 실행하지 않고 타입 힌트 원문(ast)만 비교한다.

틀린 것을 실행 전에 막되, 판단할 수 없는 것은 막지 않는다:
- 잘 알려진 구체 타입(str, int, list, dict, DataFrame ...)끼리 명백히 다를 때만 문제로 본다.
- 사용자 클래스, Any, Sequence 같은 추상 타입, 힌트가 없는 경우는 검사하지 않는다.
- int → float, bool → int처럼 파이썬이 그대로 받아 주는 것은 허용한다.
"""

from __future__ import annotations

import ast

from ms_dataflow.models import ActionSpec

KNOWN = {
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "list",
    "dict",
    "tuple",
    "set",
    "frozenset",
    "DataFrame",
    "None",
}
_ALIASES = {
    "List": "list",
    "Dict": "dict",
    "Tuple": "tuple",
    "Set": "set",
    "FrozenSet": "frozenset",
    "NoneType": "None",
}
# (보내는 쪽, 받는 쪽): 파이썬이 그대로 받아 주는 조합
_WIDENS = {("int", "float"), ("bool", "int"), ("bool", "float")}


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return _ALIASES.get(node.id, node.id)
    if isinstance(node, ast.Attribute):  # pd.DataFrame, typing.List
        return _ALIASES.get(node.attr, node.attr)
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return None


def _options(node: ast.expr) -> set[str] | None:
    """타입 힌트가 허용하는 바깥 타입 이름들. 판단할 수 없으면 None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):  # "DataFrame" (전방 참조)
        try:
            return _options(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):  # A | B
        left, right = _options(node.left), _options(node.right)
        return None if left is None or right is None else left | right
    if isinstance(node, ast.Subscript):
        outer = _name(node.value)
        if outer in ("Optional", "Union"):
            args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            out: set[str] = {"None"} if outer == "Optional" else set()
            for a in args:
                opts = _options(a)
                if opts is None:
                    return None
                out |= opts
            return out
        if outer in ("Annotated",):
            first = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            return _options(first)
        return {outer} if outer else None
    name = _name(node)
    return {name} if name else None


def parse(annotation: str | None) -> set[str] | None:
    if not annotation:
        return None
    try:
        return _options(ast.parse(annotation, mode="eval").body)
    except SyntaxError:
        return None


def output_type(spec: ActionSpec, slot: str) -> str | None:
    """출력 슬롯의 타입 힌트 원문. outputs가 여럿이면 tuple[...]의 해당 위치."""
    if not spec.returns or slot not in spec.outputs:
        return None
    if len(spec.outputs) == 1:
        return spec.returns
    try:
        node = ast.parse(spec.returns, mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Subscript) and _name(node.value) == "tuple":
        elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        i = spec.outputs.index(slot)
        if len(elts) == len(spec.outputs):
            return ast.unparse(elts[i])
    return None


def input_type(spec: ActionSpec, slot: str) -> str | None:
    return spec.arg_types.get(slot)


def compatible(sent: str | None, received: str | None) -> bool:
    """명백히 맞지 않을 때만 False. 판단할 수 없으면 True."""
    out, inp = parse(sent), parse(received)
    if out is None or inp is None:
        return True
    if not (out <= KNOWN and inp <= KNOWN):
        return True  # 사용자 클래스, Any, Sequence 등: 판단하지 않는다
    return any(o == i or (o, i) in _WIDENS for o in out for i in inp)
