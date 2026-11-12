"""공개 예외 체계. 사용자가 except로 잡는 대상이므로 API의 일부다."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


class MsdfError(Exception):
    """모든 MSDF 예외의 뿌리."""


# --- 로딩 ---------------------------------------------------------------
class LoadError(MsdfError):
    """로딩 실패. 파일, 줄, 원문, 이유, 해결 방법을 담는다."""

    def __init__(
        self,
        reason: str,
        *,
        file: str | None = None,
        line: int | None = None,
        source: str | None = None,
        fix: str | None = None,
    ) -> None:
        self.reason = reason
        self.file = file
        self.line = line
        self.source = source
        self.fix = fix
        super().__init__(self.render())

    def render(self) -> str:
        where = ""
        if self.file:
            where = f"{self.file}:{self.line}" if self.line else self.file
        lines = [f"MSDF 로딩 오류: {where}" if where else "MSDF 로딩 오류"]
        if self.source:
            lines += [f"  {s}" for s in self.source.rstrip().splitlines()]
            lines.append("")
        lines.append(f"  {self.reason}")
        if self.fix:
            lines.append(f"  고칠 방법: {self.fix}")
        return "\n".join(lines)


class DeclarationError(LoadError):
    """데코레이터 선언이 잘못됨."""


class ConfigError(LoadError):
    """DAG·IAM·resolvers YAML이 잘못됨."""


class RegistrationError(LoadError):
    """Scheduler가 등록을 거부함."""


class LoadErrors(LoadError):
    """로딩 중 발견한 오류 여러 개를 한 번에 담는다.

    첫 오류에서 멈추지 않고 모아서 보여 주기 위한 것이다. ``errors``에 개별 오류가 있다.
    """

    def __init__(self, errors: Sequence[LoadError]) -> None:
        self.errors = list(errors)
        super().__init__(f"오류 {len(self.errors)}건")

    def render(self) -> str:
        body = "\n\n".join(e.render() for e in self.errors)
        return f"MSDF 로딩 오류 {len(self.errors)}건\n\n{body}"


def raise_collected(errors: Iterable[LoadError]) -> None:
    """모은 오류가 있으면 하나면 그대로, 여럿이면 LoadErrors로 던진다."""
    errs = list(errors)
    if len(errs) == 1:
        raise errs[0]
    if errs:
        raise LoadErrors(errs)


# --- order --------------------------------------------------------------
class OrderError(MsdfError):
    """order가 받아들여지지 않음. order()가 던지는 것은 이 아래뿐이다."""

    code = "order_error"


class PermissionDenied(OrderError):
    """IAM 거부. 막힌 엣지를 담는다."""

    code = "permission_denied"

    def __init__(self, message: str, blocked: Sequence[str] = ()) -> None:
        self.blocked = list(blocked)
        super().__init__(message)


class UnknownOrder(OrderError):
    """그런 order 이름의 DAG가 없음."""

    code = "unknown_order"


class ServiceUnavailable(OrderError):
    """경로의 서비스가 떠 있지 않음."""

    code = "service_unavailable"

    def __init__(self, message: str, missing: Sequence[str] = ()) -> None:
        self.missing = list(missing)
        super().__init__(message)


class ParamError(OrderError):
    """params 이름이 맞지 않음."""

    code = "param_error"


ORDER_ERRORS: dict[str, type[OrderError]] = {
    cls.code: cls
    for cls in (OrderError, PermissionDenied, UnknownOrder, ServiceUnavailable, ParamError)
}


# --- 실행 ---------------------------------------------------------------
class ExecutionError(MsdfError):
    """단계 실행 실패."""


class ActionFailed(ExecutionError):
    """사용자 Action이 예외를 냄. 원본은 __cause__에 둔다."""


class StepCancelled(ExecutionError):
    """상위 실패로 취소됨."""


# --- 저장소 -------------------------------------------------------------
class ResolverError(MsdfError):
    """저장소 쪽 실패."""


class UnsupportedType(ResolverError):
    """직렬화할 수 없는 타입."""


class ArtifactMissing(ResolverError):
    """load했는데 본체가 없음."""
