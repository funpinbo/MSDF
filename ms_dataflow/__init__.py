"""MSDF — Micro Service Data Flow.

사용자가 쓰는 것은 이 다섯 개와, 데이터를 지울 때 쓰는 delete, source 데이터가 바뀌었다고 알리는
invalidate가 전부다.
예외는 ``ms_dataflow.errors``에 있다.
"""

from ms_dataflow.client import start
from ms_dataflow.decorators import action, context, delete, invalidate, order, service

__all__ = ["service", "action", "order", "start", "context", "delete", "invalidate"]
__version__ = "0.3.0"
