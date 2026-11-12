"""파일 시스템 Resolver (내장)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from ms_dataflow import ids
from ms_dataflow.errors import ArtifactMissing
from ms_dataflow.resolvers.base import Saved, checksum, decode, encode


class FileResolver:
    """``<path>/<id 앞 2글자>/<id>.bin`` 과 ``.meta.json``으로 저장한다."""

    def __init__(self, path: str = "./store", allow_pickle: bool = False, **_: Any) -> None:
        self.root = Path(path)
        self.allow_pickle = allow_pickle
        self.root.mkdir(parents=True, exist_ok=True)

    def _base(self, artifact_id: str) -> Path:
        return self.root / artifact_id[:2] / artifact_id

    def _index(self, lineage_key: str, generation: float) -> Path:
        return self.root / "_index" / ids.save_key(lineage_key, generation)

    @staticmethod
    def _write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, path)

    def exists(self, lineage_key: str, generation: float) -> str | None:
        idx = self._index(lineage_key, generation)
        if idx.exists():
            aid = idx.read_text().strip()
            if self._base(aid).with_suffix(".meta.json").exists():
                return aid
        return None

    def save(self, lineage_key: str, generation: float, data: Any, parents: list[str]) -> Saved:
        aid = ids.artifact_id(parents, lineage_key, generation)
        base = self._base(aid)
        meta_path = base.with_suffix(".meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            return Saved(aid, str(base.with_suffix(".bin")), meta["checksum"], meta["nbytes"])
        kind, raw = encode(data, self.allow_pickle)
        digest = checksum(raw)
        self._write(base.with_suffix(".bin"), raw)
        meta = {
            "kind": kind,
            "lineage_key": lineage_key,
            "generation": generation,
            "checksum": digest,
            "nbytes": len(raw),
        }
        self._write(meta_path, json.dumps(meta).encode())  # 메타가 마지막: 여기까지 와야 저장 완료
        self._write(self._index(lineage_key, generation), aid.encode())
        return Saved(aid, str(base.with_suffix(".bin")), digest, len(raw))

    def load(self, artifact_id: str) -> Any:
        base = self._base(artifact_id)
        meta_path = base.with_suffix(".meta.json")
        try:
            meta = json.loads(meta_path.read_text())
            raw = base.with_suffix(".bin").read_bytes()
        except FileNotFoundError:
            raise ArtifactMissing(f"{artifact_id}의 데이터가 {self.root}에 없습니다") from None
        return decode(meta["kind"], raw)

    def locate(self, artifact_id: str) -> str:
        return str(self._base(artifact_id).with_suffix(".bin"))

    def delete(self, artifact_id: str) -> None:
        base = self._base(artifact_id)
        for suffix in (".bin", ".meta.json"):
            p = base.with_suffix(suffix)
            if p.exists():
                p.unlink()

    def close(self) -> None:
        pass

    def clear(self) -> None:  # 테스트용
        shutil.rmtree(self.root, ignore_errors=True)
