import pytest

from app.telemetry import ffmpeg_io


def test_missing_ffmpeg_raises_clear_error(monkeypatch):
    monkeypatch.setattr(ffmpeg_io.shutil, "which", lambda name: None)
    with pytest.raises(ffmpeg_io.MissingToolError) as excinfo:
        ffmpeg_io.require_ffmpeg()
    message = str(excinfo.value)
    assert "ffmpeg" in message and "ffprobe" in message
    assert "PATH" in message
    assert "winget" in message


def test_only_missing_tool_is_named(monkeypatch):
    def fake_which(name):
        return None if name == "ffprobe" else f"C:/bin/{name}.exe"

    monkeypatch.setattr(ffmpeg_io.shutil, "which", fake_which)
    with pytest.raises(ffmpeg_io.MissingToolError) as excinfo:
        ffmpeg_io.require_ffmpeg()
    assert "ffprobe" in str(excinfo.value)
    assert "ffmpeg," not in str(excinfo.value)


def test_present_tools_pass(monkeypatch):
    monkeypatch.setattr(ffmpeg_io.shutil, "which", lambda name: f"/bin/{name}")
    ffmpeg_io.require_ffmpeg()
