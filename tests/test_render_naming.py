from pathlib import Path

from app.render.naming import export_stem, reserve_output


def test_stem_names_clip_overlays_and_range():
    stem = export_stem(Path("videos/DJI_20261026155823_0051_D.MP4"), ["timestamp", "lean"], 300, 330.5)
    assert stem == "DJI_20261026155823_0051_D__timestamp+lean__300-330.5"


def test_whole_clip_range_uses_whole_numbers():
    stem = export_stem(Path("clip.MP4"), ["lean"], 0.0, 60.0)
    assert stem == "clip__lean__0-60"


def test_repeated_export_gets_numeric_suffixes_and_never_overwrites(tmp_path):
    stem = "clip__lean__300-330"
    first = reserve_output(tmp_path, stem)
    first.write_bytes(b"first export")
    second = reserve_output(tmp_path, stem)
    third = reserve_output(tmp_path, stem)

    assert [p.name for p in (first, second, third)] == [
        "clip__lean__300-330.mp4",
        "clip__lean__300-330_2.mp4",
        "clip__lean__300-330_3.mp4",
    ]
    assert first.read_bytes() == b"first export"
    assert second.exists() and third.exists()


def test_reserve_creates_the_exports_folder(tmp_path):
    folder = tmp_path / "exports"
    path = reserve_output(folder, "clip")
    assert path.parent == folder and path.exists()
