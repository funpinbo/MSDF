"""공개 예외 체계. 사용자가 except로 잡는 대상이므로 API의 일부다."""


class MsdfError(Exception):
    """모든 MSDF 예외의 뿌리."""


# --- 로딩 ---------------------------------------------------------------
class LoadError(MsdfError):
    """로딩 실패. 파일, 줄, 원문, 이유, 해결 방법을 담는다."""


class DeclarationError(LoadError):
    """데코레이터 선언이 잘못됨."""


class ConfigError(LoadError):
    """DAG·IAM·resolvers YAML이 잘못됨."""


class RegistrationError(LoadError):
    """Scheduler가 등록을 거부함."""


# --- order --------------------------------------------------------------
class OrderError(MsdfError):
    """order가 받아들여지지 않음. order()가 던지는 것은 이 아래뿐이다."""


class PermissionDenied(OrderError):
    """IAM 거부. 막힌 엣지를 담는다."""


class UnknownOrder(OrderError):
    """그런 order 이름의 DAG가 없음."""


class ServiceUnavailable(OrderError):
    """경로의 서비스가 떠 있지 않음."""


class ParamError(OrderError):
    """params 이름이 맞지 않음."""


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
