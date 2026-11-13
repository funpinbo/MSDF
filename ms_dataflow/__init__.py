"""MSDF — Micro Service Data Flow.

사용자가 쓰는 것은 이 다섯 개와, 데이터를 지우는 delete, source 데이터가 바뀌었다고 알리는
invalidate, 요청이나 구독을 끝내는 cancel이 전부다.
예외는 ``ms_dataflow.errors``에 있다.
"""

from ms_dataflow.client import start
from ms_dataflow.decorators import (
    action,
    cancel,
    context,
    delete,
    invalidate,
    order,
    service,
)

__all__ = ["service", "action", "order", "start", "context", "delete", "invalidate", "cancel"]
__version__ = "0.5.1"
