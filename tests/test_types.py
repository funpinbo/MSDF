"""0.5: DAG로 잇는 슬롯의 타입 힌트가 명백히 다르면 실행 전에 막는다."""

from __future__ import annotations

import textwrap

import pytest

from ms_dataflow.config.types import compatible, output_type
from ms_dataflow.errors import LoadError
from ms_dataflow.models import ActionSpec
from ms_dataflow.project import load_project


@pytest.mark.parametrize(
    "sent,received",
    [
        ("list", "list"),
        ("list[dict]", "list"),
        ("List[int]", "list"),
        ("int", "float"),  # 넓히는 것은 허용
        ("bool", "int"),
        ("pd.DataFrame", "DataFrame"),
        ("DataFrame | None", "DataFrame"),
        ("Optional[str]", "str"),
        ("str", "str | bytes"),
        ("'DataFrame'", "DataFrame"),  # 전방 참조
        ("MyRecord", "dict"),  # 사용자 클래스: 판단하지 않는다
        ("dict", "Mapping[str, int]"),  # 추상 타입: 판단하지 않는다
        ("list", "Any"),
        (None, "dict"),  # 힌트 없음
        ("Annotated[list, 'x']", "list"),
    ],
)
def test_compatible(sent, received):
    assert compatible(sent, received)


@pytest.mark.parametrize(
    "sent,received",
    [
        ("list", "dict"),
        ("str", "int"),
        ("float", "int"),
        ("DataFrame", "list"),
        ("dict | None", "str"),
    ],
)
def test_clear_mismatch(sent, received):
    assert not compatible(sent, received)


def test_output_type_of_multiple_outputs():
    spec = ActionSpec(
        service="s",
        name="a",
        version="v",
        file="f",
        lineno=1,
        outputs=("summary", "keywords"),
        returns="tuple[str, list[str]]",
    )
    assert output_type(spec, "summary") == "str"
    assert output_type(spec, "keywords") == "list[str]"


def write(root, name, text):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))


def project(tmp_path, clean_arg="rows: list", stats_ret="dict", on_stats_arg="stats: dict"):
    write(
        tmp_path,
        "src.py",
        """
        from ms_dataflow import action, service
        service("src")

        @action(params=["day"], outputs=["rows"])
        def load(day: str) -> list[dict]:
            return []
    """,
    )
    write(
        tmp_path,
        "tr.py",
        f"""
        from ms_dataflow import action, service
        service("tr")

        @action(inputs=["rows"], outputs=["stats"])
        def summarize({clean_arg}) -> {stats_ret}:
            return {{}}
    """,
    )
    write(
        tmp_path,
        "app.py",
        f"""
        from ms_dataflow import action, order, service

        @service("app")
        def app(day):
            order("s", params={{"day": day}})

        @action(inputs=["stats"])
        def on_stats({on_stats_arg}): ...

        @action
        def on_fail(status): ...
    """,
    )
    write(
        tmp_path,
        "dags/s.yaml",
        """
        order: s
        nodes:
          load: {service: src, action: load}
          summarize: {service: tr, action: summarize}
        edges:
          - {from: load.rows, to: summarize.rows}
        result: summarize.stats
        deliveries:
          - {requester: app, on_success: app.on_stats, on_fail: app.on_fail}
    """,
    )
    return load_project(tmp_path)


def test_matching_types_load(tmp_path):
    project(tmp_path)


def test_edge_type_mismatch_is_a_load_error(tmp_path):
    with pytest.raises(LoadError) as e:
        project(tmp_path, clean_arg="rows: dict")
    text = e.value.render()
    assert "load.rows → summarize.rows" in text and "'list[dict]'" in text and "'dict'" in text
    assert "tr.py" in text and "고칠 방법" in text


def test_result_type_mismatch_with_on_success(tmp_path):
    with pytest.raises(LoadError) as e:
        project(tmp_path, on_stats_arg="stats: str")
    assert "on_success 'app.on_stats'" in e.value.render()


def test_unjudgeable_hints_are_not_errors(tmp_path):
    project(tmp_path, clean_arg="rows: 'Records'", stats_ret="Summary", on_stats_arg="stats")
