# tests/unit/test_cli.py
from pathlib import Path
from click.testing import CliRunner
from materia_epd import cli


def _setup_dirs(tmp_path: Path):
    gen = tmp_path / "gen"
    epd = tmp_path / "epds"
    gen.mkdir()
    epd.mkdir()
    return gen, epd


def test_no_output_path_calls_pipeline_with_none(monkeypatch, tmp_path):
    runner = CliRunner()
    gen, epd = _setup_dirs(tmp_path)

    called = {}

    def fake_run_materia(a, b, c, **kwargs):
        called["a"] = a
        called["b"] = b
        called["c"] = c
        called["kwargs"] = kwargs

    monkeypatch.setattr(cli, "run_materia", fake_run_materia, raising=True)

    result = runner.invoke(cli.aggregate, [str(gen), str(epd)])
    assert result.exit_code == 0
    assert called["a"] == gen
    assert called["b"] == epd
    assert called["c"] is None
    assert called["kwargs"]["use_epd_cache"] is True


def test_with_output_path_calls_pipeline_with_path(monkeypatch, tmp_path):
    runner = CliRunner()
    gen, epd = _setup_dirs(tmp_path)
    out = tmp_path / "out" / "file.xml"

    called = {}

    def fake_run_materia(a, b, c, **kwargs):
        called["a"] = a
        called["b"] = b
        called["c"] = c
        called["kwargs"] = kwargs

    monkeypatch.setattr(cli, "run_materia", fake_run_materia, raising=True)

    result = runner.invoke(cli.aggregate, [str(gen), str(epd), "-o", str(out)])
    assert result.exit_code == 0
    assert called["a"] == gen
    assert called["b"] == epd
    assert called["c"] == out


def test_no_epd_cache_flag(monkeypatch, tmp_path):
    runner = CliRunner()
    gen, epd = _setup_dirs(tmp_path)
    called = {}

    def fake_run_materia(a, b, c, **kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(cli, "run_materia", fake_run_materia, raising=True)

    result = runner.invoke(cli.aggregate, [str(gen), str(epd), "--no-epd-cache"])
    assert result.exit_code == 0
    assert called["kwargs"]["use_epd_cache"] is False


def test_build_cache_command(monkeypatch, tmp_path):
    runner = CliRunner()
    epd = tmp_path / "epds"
    epd.mkdir()
    cache_out = tmp_path / "my-cache"
    called = {}

    def fake_build(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(cli, "build_epd_cache", fake_build, raising=True)

    result = runner.invoke(
        cli.build_cache_cmd,
        [str(epd), "-o", str(cache_out), "--force"],
    )
    assert result.exit_code == 0
    assert called["args"][0] == epd
    assert called["kwargs"]["force"] is True


def test_main_dispatches_build_cache(monkeypatch, tmp_path):
    epd = tmp_path / "epds"
    epd.mkdir()
    captured = {}

    def fake_cmd_main(*, args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs

    monkeypatch.setattr(cli.build_cache_cmd, "main", fake_cmd_main)

    cli.main(["build-cache", str(epd)])
    assert captured["args"] == [str(epd)]
    assert captured["kwargs"]["prog_name"] == "materia_epd build-cache"
