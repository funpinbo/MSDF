from __future__ import annotations

import pytest

from ms_dataflow.config.resolvers import ResolverConfig
from ms_dataflow.errors import ArtifactMissing, ConfigError, UnsupportedType
from ms_dataflow.resolvers import ResolverPool
from ms_dataflow.resolvers.file import FileResolver
from ms_dataflow.resolvers.sqlite import SqliteResolver


@pytest.fixture(params=["file", "sqlite"])
def resolver(request, tmp_path):
    if request.param == "file":
        r = FileResolver(str(tmp_path / "store"))
    else:
        r = SqliteResolver(str(tmp_path / "store.db"))
    yield r
    r.close()


@pytest.mark.parametrize(
    "value", [{"a": [1, 2]}, [1, "x"], "text", 3, 2.5, True, None, b"\x00\x01"]
)
def test_roundtrip(resolver, value):
    s = resolver.save("lk", 1.0, value, [])
    assert resolver.load(s.artifact_id) == value
    assert resolver.exists("lk", 1.0) == s.artifact_id


def test_resave_returns_same_id_without_rewriting(resolver):
    a = resolver.save("lk", 1.0, {"v": 1}, ["p"])
    b = resolver.save("lk", 1.0, {"v": 2}, ["p"])  # 같은 (lineage, generation)이면 쓰지 않는다
    assert a.artifact_id == b.artifact_id
    assert resolver.load(a.artifact_id) == {"v": 1}


def test_missing_and_delete(resolver):
    with pytest.raises(ArtifactMissing):
        resolver.load("nope")
    s = resolver.save("lk", 2.0, [1], [])
    resolver.delete(s.artifact_id)
    with pytest.raises(ArtifactMissing):
        resolver.load(s.artifact_id)


def test_unsupported_type(resolver):
    with pytest.raises(UnsupportedType):
        resolver.save("lk", 3.0, object(), [])


def test_pickle_opt_in(tmp_path):
    r = FileResolver(str(tmp_path), allow_pickle=True)
    s = r.save("lk", 1.0, {1, 2}, [])
    assert r.load(s.artifact_id) == {1, 2}


def test_dataframe_parquet(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    r = FileResolver(str(tmp_path))
    out = r.load(r.save("lk", 1.0, df, []).artifact_id)
    assert out.equals(df)


def test_config_mapping_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_DIR", "data")
    (tmp_path / "resolvers.yaml").write_text(
        "a.b.out: {backend: sqlite, path: '${STORE_DIR}/x.db'}\ndefault: {backend: file, path: ./s}\n"
    )
    cfg = ResolverConfig.load(tmp_path / "resolvers.yaml", tmp_path)
    assert cfg.backend_for("a", "b", "out") == {
        "backend": "sqlite",
        "path": str(tmp_path / "data/x.db"),
    }
    assert cfg.backend_for("z", "z", "z") == {"backend": "file", "path": str(tmp_path / "s")}
    pool = ResolverPool()
    assert isinstance(pool.get(cfg.backend_for("a", "b", "out")), SqliteResolver)
    pool.close()


def test_config_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    (tmp_path / "resolvers.yaml").write_text("default: {backend: file, path: '${NOPE}'}\n")
    with pytest.raises(ConfigError, match="NOPE"):
        ResolverConfig.load(tmp_path / "resolvers.yaml", tmp_path)
    (tmp_path / "resolvers.yaml").write_text("default: {backend: nosuch}\n")
    with pytest.raises(ConfigError, match="nosuch"):
        ResolverConfig.load(tmp_path / "resolvers.yaml", tmp_path)
    (tmp_path / "resolvers.yaml").write_text("a.b: {backend: file}\n")
    with pytest.raises(ConfigError, match="서비스.액션.슬롯"):
        ResolverConfig.load(tmp_path / "resolvers.yaml", tmp_path)
