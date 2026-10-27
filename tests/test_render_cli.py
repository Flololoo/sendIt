import importlib

import pytest
from overlay_fixtures import make_clip

from app.render import __main__ as cli

export_mod = importlib.import_module("app.render.export")


def test_cli_rejects_invalid_range_with_exit_code_1_and_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(export_mod, "load_clip", lambda path, mount, **kwargs: make_clip(False))
    code = cli.main([
        "export", "DJI_TEST_0051_D.MP4", "--overlay", "timestamp", "--with-test-overlay",
        "--start", "30", "--end", "20", "--preset", "social",
        "--jobs-file", str(tmp_path / "jobs.json"),
    ])
    assert code == 1
    assert "must be before end" in capsys.readouterr().err


def test_cli_requires_at_least_one_overlay(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["export", "DJI_TEST_0051_D.MP4", "--jobs-file", str(tmp_path / "jobs.json")])
    assert exc.value.code == 2
    assert "--overlay" in capsys.readouterr().err
