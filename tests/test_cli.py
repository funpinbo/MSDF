from __future__ import annotations

from ms_dataflow.cli import main


def test_check_ok(calc, capsys):
    assert main(["check", "--root", str(calc)]) == 0
    out = capsys.readouterr()
    assert "서비스 3개" in out.out and "Action 5개" in out.out
    assert "iam.yaml이 없어" in out.err


def test_check_reports_errors(calc, capsys):
    dag = calc / "dags" / "number.yaml"
    dag.write_text(dag.read_text().replace("action: double}", "action: triple}"))
    assert main(["check", "--root", str(calc)]) == 1
    err = capsys.readouterr().err
    assert "MSDF 로딩 오류" in err and "triple" in err and "고칠 방법" in err


def test_external_services_are_warnings(calc, capsys):
    (calc / "src.py").unlink()
    assert main(["check", "--root", str(calc)]) == 1
    capsys.readouterr()
    assert main(["check", "--root", str(calc), "--allow-external"]) == 0
    assert "등록될 때 다시 검사" in capsys.readouterr().err
