import csv

from app.telemetry.export import COLUMNS, export_csv
from helpers import fixture_telemetry


def test_csv_has_header_and_one_row_per_sample(tmp_path):
    tel = fixture_telemetry()
    out = tmp_path / "telemetry.csv"

    written = export_csv(tel, out)

    assert written == len(tel) == 300
    with open(out, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == list(COLUMNS)
    assert len(rows) - 1 == len(tel)
    assert COLUMNS == (
        "t_s", "qw", "qx", "qy", "qz", "ax_g", "ay_g", "az_g", "iso", "shutter_s", "wb_k",
    )


def test_csv_first_row_matches_first_sample(tmp_path):
    tel = fixture_telemetry()
    out = tmp_path / "telemetry.csv"
    export_csv(tel, out)
    with open(out, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        first = next(reader)
    assert float(first["t_s"]) == 0.0
    assert float(first["iso"]) == 100.0
    assert abs(float(first["shutter_s"]) - 1 / 250) < 1e-12
    assert float(first["wb_k"]) == 9555.0
