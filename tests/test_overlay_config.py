import pytest

from overlay_fixtures import TimestampOverlay

from app.overlays.config import ConfigError, validate_config
from app.overlays.registry import OverlayRegistry


@pytest.fixture
def reg():
    r = OverlayRegistry()
    r.register(TimestampOverlay())
    return r


def _error_for(reg, config) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        validate_config(config, reg)
    return exc.value.errors


def test_defaults_are_filled_in(reg):
    resolved = validate_config({"timestamp": {}}, reg)
    cfg = resolved["timestamp"]
    assert cfg.enabled is True
    assert cfg.position == "top-left"
    assert cfg.size == "M"
    assert cfg.settings == {"decimals": 2, "unit": "s"}


def test_given_values_override_defaults(reg):
    cfg = validate_config(
        {"timestamp": {"enabled": False, "position": "bottom-right", "size": "L",
                       "settings": {"decimals": 0}}},
        reg,
    )["timestamp"]
    assert cfg.enabled is False
    assert cfg.position == "bottom-right"
    assert cfg.size == "L"
    assert cfg.settings == {"decimals": 0, "unit": "s"}


def test_unknown_overlay_names_it(reg):
    errors = _error_for(reg, {"nope": {}})
    assert any("nope" in e and "unknown overlay" in e for e in errors)


def test_unknown_setting_names_it(reg):
    errors = _error_for(reg, {"timestamp": {"settings": {"colour": "red"}}})
    assert any("timestamp.settings.colour" in e for e in errors)


def test_unknown_field_names_it(reg):
    errors = _error_for(reg, {"timestamp": {"colour": "red"}})
    assert any("timestamp.colour" in e for e in errors)


def test_out_of_range_int_names_setting(reg):
    errors = _error_for(reg, {"timestamp": {"settings": {"decimals": 9}}})
    assert any("timestamp.settings.decimals" in e and "maximum" in e for e in errors)


def test_wrong_type_names_setting(reg):
    errors = _error_for(reg, {"timestamp": {"settings": {"decimals": "two"}}})
    assert any("timestamp.settings.decimals" in e for e in errors)


def test_bool_is_not_accepted_as_int(reg):
    errors = _error_for(reg, {"timestamp": {"settings": {"decimals": True}}})
    assert any("timestamp.settings.decimals" in e for e in errors)


def test_enum_value_outside_choices_names_setting(reg):
    errors = _error_for(reg, {"timestamp": {"settings": {"unit": "min"}}})
    assert any("timestamp.settings.unit" in e for e in errors)


def test_invalid_position_names_field(reg):
    errors = _error_for(reg, {"timestamp": {"position": "centre"}})
    assert any("timestamp.position" in e for e in errors)


def test_invalid_size_names_field(reg):
    errors = _error_for(reg, {"timestamp": {"size": "XL"}})
    assert any("timestamp.size" in e for e in errors)


def test_enabled_must_be_bool(reg):
    errors = _error_for(reg, {"timestamp": {"enabled": "yes"}})
    assert any("timestamp.enabled" in e for e in errors)


def test_overlay_validate_hook_rejects_cross_setting_rule(reg):
    errors = _error_for(reg, {"timestamp": {"settings": {"unit": "ms", "decimals": 2}}})
    assert errors == ["unit 'ms' requires decimals 0"]


def test_overlay_validate_hook_passes_valid_combination(reg):
    cfg = validate_config({"timestamp": {"settings": {"unit": "ms", "decimals": 0}}}, reg)
    assert cfg["timestamp"].settings == {"decimals": 0, "unit": "ms"}


def test_all_errors_are_collected(reg):
    errors = _error_for(
        reg, {"nope": {}, "timestamp": {"position": "centre", "settings": {"decimals": 9}}}
    )
    assert len(errors) == 3
