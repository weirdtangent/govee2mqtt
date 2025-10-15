# tests/test_util.py
import os
import textwrap
import builtins
import types
import pytest
import yaml
import util


# ---------- read_file ----------


def test_read_file_strips_newlines(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\n", encoding="utf-8")
    assert util.read_file(p) == "ab"


def test_read_file_no_strip(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a\nb\n", encoding="utf-8")
    assert util.read_file(p, strip_newlines=False) == "a\nb\n"


def test_read_file_default_on_missing(tmp_path):
    missing = tmp_path / "nope.txt"
    assert util.read_file(missing, default="zzz") == "zzz"


def test_read_file_raises_when_missing_and_no_default(tmp_path):
    with pytest.raises(FileNotFoundError):
        util.read_file(tmp_path / "nope.txt")


# ---------- read_version ----------
# read_version reads VERSION next to util.__file__, so we monkeypatch util.__file__


def test_read_version_from_file(tmp_path, monkeypatch):
    # Create a fake module location with VERSION
    fake_dir = tmp_path / "pkgdir"
    fake_dir.mkdir()
    (fake_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")

    # Point util.__file__ into our fake dir
    monkeypatch.setattr(util, "__file__", str(fake_dir / "util.py"))
    assert util.read_version() == "1.2.3"


def test_read_version_empty_file_is_unknown(tmp_path, monkeypatch):
    fake_dir = tmp_path / "pkgdir"
    fake_dir.mkdir()
    (fake_dir / "VERSION").write_text("", encoding="utf-8")

    monkeypatch.setattr(util, "__file__", str(fake_dir / "util.py"))
    assert util.read_version() == "unknown"


def test_read_version_env_fallback(tmp_path, monkeypatch):
    fake_dir = tmp_path / "pkgdir"
    fake_dir.mkdir()
    # No VERSION file

    monkeypatch.setattr(util, "__file__", str(fake_dir / "util.py"))
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    assert util.read_version() == "9.9.9"


def test_read_version_unknown_when_no_file_and_no_env(tmp_path, monkeypatch):
    fake_dir = tmp_path / "pkgdir"
    fake_dir.mkdir()

    monkeypatch.setattr(util, "__file__", str(fake_dir / "util.py"))
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert util.read_version() == "unknown"


# ---------- number_to_rgb (legacy linear R↔G, no blue) ----------


@pytest.mark.parametrize(
    "number,max_value,expected",
    [
        (0, 100, {"r": 255, "g": 0, "b": 0}),  # pure red
        (100, 100, {"r": 0, "g": 255, "b": 0}),  # pure green
        (
            50,
            100,
            {"r": 127, "g": 127, "b": 0},
        ),  # midpoint, no blue (keeps your original behavior)
        (-10, 100, {"r": 255, "g": 0, "b": 0}),  # clamped low
        (200, 100, {"r": 0, "g": 255, "b": 0}),  # clamped high
    ],
)
def test_number_to_rgb_basic(number, max_value, expected):
    assert util.number_to_rgb_linear(number, max_value) == expected


@pytest.mark.parametrize("bad_max", [0, -1, None])
def test_number_to_rgb_bad_max_raises(bad_max):
    with pytest.raises(ValueError):
        util.number_to_rgb_linear(10, bad_max)


# ---------- number_to_rgb_bluepop (R↔G with blue peaking at midpoint) ----------


def test_number_to_rgb_bluepop_endpoints_and_mid():
    # 0 → red, 1 → green, 0.5 → strong blue accent
    assert util.number_to_rgb_bluepop(0, 100) == {"r": 255, "g": 0, "b": 0}
    assert util.number_to_rgb_bluepop(100, 100) == {"r": 0, "g": 255, "b": 0}
    # Uses rounding, so midpoint r/g will be 128
    assert util.number_to_rgb_bluepop(50, 100) == {"r": 128, "g": 128, "b": 255}


def test_number_to_rgb_bluepop_brightness_scaling():
    # brightness rescales so max channel == brightness
    c = util.number_to_rgb_bluepop(50, 100, brightness=200)
    assert c == {"r": 100, "g": 100, "b": 200}


def test_number_to_rgb_bluepop_clamps_and_validates():
    # clamps number into [0, max]
    assert util.number_to_rgb_bluepop(-5, 100) == {"r": 255, "g": 0, "b": 0}
    assert util.number_to_rgb_bluepop(150, 100) == {"r": 0, "g": 255, "b": 0}
    # bad max_value
    with pytest.raises(ValueError):
        util.number_to_rgb_bluepop(10, 0)


# ---------- number_to_rgb_hsv (hue sweep red→yellow→green) ----------


def test_number_to_rgb_hsv_endpoints_and_mid():
    # 0 → red
    assert util.number_to_rgb_hsv(0, 100) == {"r": 255, "g": 0, "b": 0}
    # 50% → yellow
    assert util.number_to_rgb_hsv(50, 100) == {"r": 255, "g": 255, "b": 0}
    # 100% → green
    assert util.number_to_rgb_hsv(100, 100) == {"r": 0, "g": 255, "b": 0}


def test_number_to_rgb_hsv_saturation_and_value_controls():
    # Desaturated becomes gray; value controls brightness.
    gray = util.number_to_rgb_hsv(25, 100, value=0.5, saturation=0.0)
    assert gray == {"r": 128, "g": 128, "b": 128}


def test_number_to_rgb_hsv_validates():
    with pytest.raises(ValueError):
        util.number_to_rgb_hsv(10, 0)


# ---------- rgb_to_number ----------


def test_rgb_to_number_from_dict():
    assert util.rgb_to_number({"r": 255, "g": 0, "b": 255}) == 0xFF00FF


def test_rgb_to_number_from_list():
    assert util.rgb_to_number([0, 128, 255]) == 0x0080FF


def test_rgb_to_number_raises_on_bad_type():
    with pytest.raises(ValueError):
        util.rgb_to_number("not-an-rgb")


# ---------- find_key_by_value ----------


def test_find_key_by_value_found():
    d = {"a": 1, "b": 2}
    assert util.find_key_by_value(d, 2) == "b"


def test_find_key_by_value_not_found():
    d = {"a": 1, "b": 2}
    assert util.find_key_by_value(d, 3) is None


# ---------- load_config ----------
# We verify:
# - reading from a directory containing config.yaml
# - reading from a direct file path
# - fallback to env when file missing
# - file values beat env vars when file exists
# - tls_enabled parsing
# - required api_key enforcement

SAMPLE_YAML = textwrap.dedent(
    """
    mqtt:
      host: filehost
      port: 2883
      qos: 1
      username: fileuser
      password: filepass
      tls_enabled: true
      prefix: govee2mqtt
      discovery_prefix: homeassistant
    govee:
      api_key: FILE_API_KEY
      device_interval: 11
      device_boost_interval: 2
      device_list_interval: 222
    debug: true
    hide_ts: false
    timezone: America/New_York
    """
).strip()


def _write_yaml(path, text=SAMPLE_YAML):
    path.write_text(text, encoding="utf-8")


def _point_version_to(tmp_path, monkeypatch, version_text="2.0.0"):
    # ensure read_version reads from our fake dir with VERSION
    fake_dir = tmp_path / "pkgdir"
    fake_dir.mkdir(exist_ok=True)
    (fake_dir / "VERSION").write_text(version_text, encoding="utf-8")
    monkeypatch.setattr(util, "__file__", str(fake_dir / "util.py"))


def test_load_config_from_directory(tmp_path, monkeypatch):
    _point_version_to(tmp_path, monkeypatch, "2.0.0")
    cfg_dir = tmp_path / "conf"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.yaml"
    _write_yaml(cfg_file)

    # Env vars should NOT override file values when present in file
    monkeypatch.setenv("MQTT_HOST", "envhost")
    monkeypatch.setenv("GOVEE_API_KEY", "ENV_API_KEY")

    config = util.load_config(str(cfg_dir))
    assert config["config_from"] == "file"
    assert config["config_path"] == str(cfg_dir.resolve())
    assert config["version"] == "2.0.0"
    assert config["mqtt"]["host"] == "filehost"  # file beats env
    assert config["govee"]["api_key"] == "FILE_API_KEY"  # file beats env
    assert config["mqtt"]["tls_enabled"] is True
    assert config["timezone"] == "America/New_York"
    assert config["debug"] is True
    assert config["govee"]["device_interval"] == 11


def test_load_config_from_file_path(tmp_path, monkeypatch):
    _point_version_to(tmp_path, monkeypatch, "3.1.4")
    cfg_dir = tmp_path / "conf"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "custom.yaml"
    _write_yaml(cfg_file)

    config = util.load_config(str(cfg_file))
    assert config["config_from"] == "file"
    assert config["config_path"] == str(cfg_dir.resolve())
    assert config["version"] == "3.1.4"
    assert config["mqtt"]["port"] == 2883


def test_load_config_env_only_when_file_missing(tmp_path, monkeypatch):
    _point_version_to(tmp_path, monkeypatch, "0.9.0")

    # No file anywhere; use env
    monkeypatch.setenv("GOVEE_API_KEY", "ENV_API_ONLY")
    monkeypatch.setenv("MQTT_HOST", "envhost")
    monkeypatch.setenv("MQTT_TLS_ENABLED", "true")
    monkeypatch.setenv("TZ", "UTC")

    missing_path = tmp_path / "no_such_dir"
    config = util.load_config(str(missing_path))

    assert config["config_from"] == "env"
    assert config["govee"]["api_key"] == "ENV_API_ONLY"
    assert config["mqtt"]["host"] == "envhost"
    assert config["mqtt"]["tls_enabled"] is True
    assert config["version"] == "0.9.0"


def test_load_config_tls_enabled_false_when_env_false_and_no_file(
    tmp_path, monkeypatch
):
    _point_version_to(tmp_path, monkeypatch)
    monkeypatch.setenv("GOVEE_API_KEY", "ENV_API_ONLY")
    monkeypatch.setenv("MQTT_TLS_ENABLED", "false")

    config = util.load_config(str(tmp_path / "missing.yaml"))
    assert config["mqtt"]["tls_enabled"] is False


def test_load_config_raises_when_api_key_missing(tmp_path, monkeypatch):
    _point_version_to(tmp_path, monkeypatch)

    # Create a config file with no govee.api_key and no env fallback
    cfg_dir = tmp_path / "conf"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.yaml"
    _write_yaml(
        cfg_file,
        text=textwrap.dedent(
            """
            mqtt:
              host: filehost
            govee:
              device_interval: 10
            """
        ).strip(),
    )
    monkeypatch.delenv("GOVEE_API_KEY", raising=False)

    with pytest.raises(ValueError):
        util.load_config(str(cfg_dir))
