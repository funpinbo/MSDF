"""단계 하나를 실제로 실행한다. LocalRunner와 Worker가 같은 코드를 쓴다."""

from __future__ import annotations

import asyncio
import inspect
import traceback
from collections.abc import Callable, Sequence
from typing import Any

from ms_dataflow.decorators import resolve_function
from ms_dataflow.errors import ArtifactMissing, MsdfError
from ms_dataflow.models import ActionSpec, SavedOutput, StepResult, StepTask
from ms_dataflow.resolvers import ResolverPool


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(*args, **kwargs))
    return fn(*args, **kwargs)


def _error(task: StepTask, kind: str, message: str, lost: str | None = None) -> StepResult:
    return StepResult(
        run_id=task.run_id,
        step_no=task.step_no,
        ok=False,
        error=message,
        error_kind=kind,  # type: ignore[arg-type]
        lost_artifact=lost,
    )


def run_task(
    task: StepTask,
    spec: ActionSpec,
    pool: ResolverPool,
    roots: Sequence[str] = (),
) -> StepResult:
    try:
        fn = resolve_function(spec.file, spec.name, roots)
    except Exception as e:  # noqa: BLE001
        return _error(task, "other", f"Action을 불러오지 못했습니다: {e}")

    # 입력 읽기
    kwargs: dict[str, Any] = {}
    for slot, ref in task.inputs.items():
        try:
            kwargs[slot] = pool.get(ref.backend).load(ref.artifact_id)
        except ArtifactMissing as e:
            return _error(task, "lost", str(e), lost=ref.artifact_id)
        except Exception as e:  # noqa: BLE001
            return _error(task, "other", f"입력 '{slot}'을 읽지 못했습니다: {e}")

    # 실행
    try:
        if task.kind == "deliver_fail":
            value = _call(fn, task.status or "failed")
        else:
            value = _call(fn, **kwargs, **task.params)
    except Exception:  # noqa: BLE001 - 사용자 예외는 삼키지 않고 원문을 남긴다
        return _error(task, "action", traceback.format_exc(limit=8))

    if task.kind != "produce":
        return StepResult(run_id=task.run_id, step_no=task.step_no, ok=True)

    # 출력 저장
    slots = list(task.outputs)
    if len(spec.outputs) == 1:
        values = {spec.outputs[0]: value}
    else:
        if not isinstance(value, (tuple, list)) or len(value) != len(spec.outputs):
            got = len(value) if isinstance(value, (tuple, list)) else 1
            return _error(
                task,
                "action",
                f"반환값이 {got}개인데 outputs는 {len(spec.outputs)}개입니다 "
                f"({', '.join(spec.outputs)}).",
            )
        values = dict(zip(spec.outputs, value, strict=True))
    parents = sorted(ref.artifact_id for ref in task.inputs.values())
    saved: list[SavedOutput] = []
    for slot in slots:
        out = task.outputs[slot]
        try:
            s = pool.get(out.backend).save(
                out.lineage_key, float(task.generation or 0.0), values[slot], parents
            )
        except MsdfError as e:
            return _error(task, "other", f"출력 '{slot}' 저장 실패: {e}")
        except Exception as e:  # noqa: BLE001
            return _error(task, "action", f"출력 '{slot}' 저장 실패: {e}")
        saved.append(
            SavedOutput(
                slot=slot,
                artifact_id=s.artifact_id,
                lineage_key=out.lineage_key,
                location=s.location,
                checksum=s.checksum,
                nbytes=s.nbytes,
            )
        )
    return StepResult(run_id=task.run_id, step_no=task.step_no, ok=True, outputs=tuple(saved))
