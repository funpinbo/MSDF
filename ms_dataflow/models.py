"""Pydantic 모델. YAML 검증, HTTP 스키마, 레지스트리 내부 표현이 모두 같은 타입을 쓴다."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
)

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w)?\s*$")
_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, None: 1}


def parse_duration(value: Any) -> timedelta | None:
    """ "30m", "1d", 90(초) 같은 값을 timedelta로."""
    if value is None or isinstance(value, timedelta):
        return value
    if isinstance(value, bool):
        raise ValueError("기간은 '30m', '1d' 같은 문자열이어야 합니다")
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    if isinstance(value, str):
        m = _DURATION.match(value)
        if m:
            return timedelta(seconds=float(m.group(1)) * _UNITS[m.group(2)])
        if value.startswith(("P", "-P")):  # JSON으로 오간 ISO 8601 기간
            return TypeAdapter(timedelta).validate_python(value)
    raise ValueError(f"기간 형식이 아닙니다: {value!r} ('30s', '30m', '1h', '1d', '1w')")


Duration = Annotated[timedelta | None, BeforeValidator(parse_duration)]

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_REF = re.compile(rf"^{_NAME}\.{_NAME}$")
_PATTERN = re.compile(r"^[A-Za-z0-9_*?]+(\.[A-Za-z0-9_*?]+){0,2}$")


def _check_ref(value: str) -> str:
    if not _REF.match(value):
        raise ValueError(f"'이름.이름' 형식이어야 합니다: {value!r}")
    return value


def _check_pattern(value: str) -> str:
    if not _PATTERN.match(value):
        raise ValueError(f"'서비스.액션' 패턴이어야 합니다 (* 사용 가능): {value!r}")
    return value


SlotRef = Annotated[str, AfterValidator(_check_ref)]
"""``node.slot``"""
ActionRef = Annotated[str, AfterValidator(_check_ref)]
"""``service.action``"""
ActionPattern = Annotated[str, AfterValidator(_check_pattern)]
"""``service.action`` 또는 ``service.*`` 같은 패턴"""


def split_ref(ref: str) -> tuple[str, str]:
    a, b = ref.split(".", 1)
    return a, b


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- 선언 -----------------------------------------------------------------
class ActionSpec(Frozen):
    """데코레이터가 선언한 Action 메타. ast 분석으로 만든다."""

    service: str
    name: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ("out",)
    params: tuple[str, ...] = ()
    version: str
    retries: int = 0
    retry_delay: float = 0.0
    fresh_for: Duration = None
    file: str
    lineno: int
    args: tuple[str, ...] = ()
    is_async: bool = False
    # 타입 힌트 원문 (코드를 실행하지 않고 ast에서 읽는다). DAG 연결의 타입 검사에 쓴다
    arg_types: dict[str, str] = Field(default_factory=dict)
    returns: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.service}.{self.name}"


class ServiceSpec(Frozen):
    name: str
    file: str
    lineno: int
    actions: tuple[str, ...] = ()
    orders: tuple[str, ...] = ()
    files: tuple[str, ...] = ()


# --- DAG -------------------------------------------------------------------
class DagNode(Frozen):
    service: str
    action: str
    fresh_for: Duration = None
    retries: int | None = None
    retry_delay: float | None = None
    # version은 없다. 선언하면 extra="forbid"에 걸려 로딩 오류가 된다.


class Edge(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    from_: SlotRef = Field(alias="from")
    to: SlotRef


class Delivery(Frozen):
    requester: str
    on_success: ActionRef
    on_fail: ActionRef  # Optional이 아니다. 빠지면 검증 실패


class Dag(Frozen):
    order: str
    nodes: dict[str, DagNode]
    edges: tuple[Edge, ...] = ()
    result: SlotRef
    deliveries: tuple[Delivery, ...] = Field(min_length=1)
    layout: dict[str, tuple[float, float]] = Field(default_factory=dict)  # 편집기의 노드 위치
    source: str | None = Field(default=None, exclude=True)


# --- 실행 ------------------------------------------------------------------
class Order(Frozen):
    name: str
    params: dict[str, JsonValue] = Field(default_factory=dict)
    requester: str
    context: dict[str, str] = Field(default_factory=dict)
    # 결과와 함께 돌려줄 값. cache key 아님
    meta: dict[str, JsonValue] = Field(default_factory=dict)
    idempotency_key: str | None = None
    subscribe: float | None = None  # 구독 기간(초). 0 = 만료 없음, None = 구독하지 않음


META_MAX_BYTES = 4096


StepKind = Literal["produce", "deliver", "deliver_fail"]
# skipped: 구독 refresh의 결과가 지난번 배달과 같아 배달하지 않은 deliver 단계
StepStatus = Literal[
    "queued", "leased", "running", "saved", "done", "failed", "cancelled", "skipped"
]
ACTIVE: tuple[StepStatus, ...] = ("queued", "leased", "running", "saved")


class InputRef(Frozen):
    artifact_id: str
    backend: dict[str, Any] = Field(default_factory=dict)


class OutputRef(Frozen):
    lineage_key: str
    backend: dict[str, Any] = Field(default_factory=dict)


class StepTask(Frozen):
    """Scheduler가 Worker에 보내는 실행 지시."""

    run_id: str
    step_no: int
    kind: StepKind
    service: str
    action: str
    generation: float | None = None
    inputs: dict[str, InputRef] = Field(default_factory=dict)
    params: dict[str, JsonValue] = Field(default_factory=dict)
    outputs: dict[str, OutputRef] = Field(default_factory=dict)
    status: str | None = None  # deliver_fail일 때 "failed" | "cancelled"
    attempt: int = 1
    # deliver / deliver_fail만: 어느 요청의 결과인지
    request_id: str | None = None
    meta: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None  # deliver_fail일 때 실패 사유 (마지막 줄)
    refresh: int = 0  # 구독: 0 = 처음 배달, 1, 2, ... = source가 바뀌어 다시 배달


class SavedOutput(Frozen):
    slot: str
    artifact_id: str
    lineage_key: str
    location: str
    checksum: str
    nbytes: int = 0


ErrorKind = Literal["action", "lost", "other"]


class StepResult(Frozen):
    run_id: str
    step_no: int
    ok: bool
    outputs: tuple[SavedOutput, ...] = ()
    error: str | None = None
    error_kind: ErrorKind | None = None
    lost_artifact: str | None = None


class Settings(Frozen):
    """시간 값과 보관 정책. 전부 설정으로 바꿀 수 있다."""

    lease_ttl: float = 60.0
    heartbeat_every: float = 20.0
    reaper_every: float = 10.0
    keep_generations: int = 3  # N: 같은 요청의 최신 generation 몇 개를 hot에 둘지
    keep_versions: int = 3  # M: 같은 자리에서 version만 다른 복제본 몇 개를 hot에 둘지
    max_replans: int = 3
    refresh_min_gap: float = 1.0  # 구독 refresh 사이 최소 간격(초)
    max_subscriptions: int = 1000  # 동시에 살아 있는 구독 수 상한
    subscription_idle: float = 600.0  # 요청 서비스가 이만큼(초) 연결되지 않으면 구독을 끝낸다


# --- 엔진 ↔ 서비스 HTTP ----------------------------------------------------
class RegisterRequest(Frozen):
    instance_id: str
    address: str
    services: tuple[ServiceSpec, ...]
    actions: tuple[ActionSpec, ...]
    context_keys: tuple[str, ...] | None = None  # @context가 없으면 None


class RegisterResponse(Frozen):
    instance_id: str
    settings: Settings
    warnings: tuple[str, ...] = ()


class OrderRequest(Frozen):
    instance_id: str
    requester: str
    name: str
    params: dict[str, JsonValue] = Field(default_factory=dict)
    context: dict[str, str] = Field(default_factory=dict)
    meta: dict[str, JsonValue] = Field(default_factory=dict)
    idempotency_key: str | None = None
    subscribe: float | None = None


class OrderResponse(Frozen):
    run_id: str  # = request_id
    lineage_key: str
    existing: bool = False  # idempotency_key로 기존 요청을 돌려줬는지


class ResultReport(Frozen):
    instance_id: str
    result: StepResult


class CancelRequest(Frozen):
    instance_id: str
    requester: str  # 자기 서비스가 낸 요청만 취소할 수 있다
    request_id: str


class InvalidateRequest(Frozen):
    instance_id: str
    requester: str  # 자기 서비스의 Action만 무효로 할 수 있다
    action: str
    params: dict[str, JsonValue] | None = None
    data_version: str | None = None


class DeleteRequest(Frozen):
    instance_id: str
    requester: str
    lineage_key: str
    cascade: bool = False
    context: dict[str, str] = Field(default_factory=dict)
