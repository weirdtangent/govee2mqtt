# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import signal
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from govee2mqtt.mixins.helpers import ConfigError, HelpersMixin


# ---------------------------------------------------------------------------
# Fake class that composes HelpersMixin with the minimal attributes it needs
# ---------------------------------------------------------------------------
class FakeHelpers(HelpersMixin):
    def __init__(self) -> None:
        self.logger = MagicMock()
        self.running = True
        self.devices: dict[str, Any] = {}
        self.states: dict[str, Any] = {}

    # save_state is called by _handle_signal; stub it out
    def save_state(self) -> None:
        pass


# ===========================================================================
# TestLoadConfigFromFile
# ===========================================================================
class TestLoadConfigFromFile:
    def test_load_valid_yaml(self, tmp_path: Any) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "mqtt": {"host": "mqtt.example.com", "port": 1884},
                    "govee": {"api_key": "file-api-key-99999"},
                }
            )
        )

        fake = FakeHelpers()
        config = fake.load_config(str(tmp_path))

        assert config["mqtt"]["host"] == "mqtt.example.com"
        assert config["mqtt"]["port"] == 1884
        assert config["govee"]["api_key"] == "file-api-key-99999"
        assert config["config_from"] == "file"


# ===========================================================================
# TestLoadConfigDefaults
# ===========================================================================
class TestLoadConfigDefaults:
    def test_defaults_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        monkeypatch.setenv("GOVEE_API_KEY", "env-api-key-11111")
        # Point to a directory that has no config.yaml so env fallback kicks in
        monkeypatch.setenv("APP_VERSION", "1.2.3")

        fake = FakeHelpers()
        config = fake.load_config(str(tmp_path))

        assert config["mqtt"]["host"] == "localhost"
        assert config["mqtt"]["port"] == 1883
        assert config["mqtt"]["qos"] == 0
        assert config["mqtt"]["prefix"] == "govee2mqtt"
        assert config["mqtt"]["protocol_version"] == "5"
        assert config["mqtt"]["discovery_prefix"] == "homeassistant"
        assert config["govee"]["api_key"] == "env-api-key-11111"
        assert config["config_from"] == "env"


# ===========================================================================
# TestLoadConfigValidation
# ===========================================================================
class TestLoadConfigValidation:
    def test_missing_api_key_raises_config_error(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """govee.api_key is mandatory; omitting it must raise ConfigError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"mqtt": {"host": "localhost"}, "govee": {}}))
        # Ensure the env var is also unset
        monkeypatch.delenv("GOVEE_API_KEY", raising=False)

        fake = FakeHelpers()
        with pytest.raises(ConfigError, match="api_key"):
            fake.load_config(str(tmp_path))

    def test_mqtt_defaults_always_present(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even without explicit mqtt section, host/port defaults prevent ConfigError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"govee": {"api_key": "valid-key"}}))

        fake = FakeHelpers()
        config = fake.load_config(str(tmp_path))
        assert config["mqtt"]["host"] == "localhost"
        assert config["mqtt"]["port"] == 1883


# ===========================================================================
# TestLoadConfigVersion
# ===========================================================================
class TestLoadConfigVersion:
    def test_app_version_env(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_VERSION", "5.6.7")
        monkeypatch.setenv("GOVEE_API_KEY", "key")

        fake = FakeHelpers()
        config = fake.load_config(str(tmp_path))
        assert config["version"] == "5.6.7"

    def test_app_tier_dev_appends_dev(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_VERSION", "1.0.0")
        monkeypatch.setenv("APP_TIER", "dev")
        monkeypatch.setenv("GOVEE_API_KEY", "key")

        fake = FakeHelpers()
        config = fake.load_config(str(tmp_path))
        assert config["version"] == "1.0.0:DEV"


# ===========================================================================
# TestRgbToNumber
# ===========================================================================
class TestRgbToNumber:
    def test_red_list(self) -> None:
        fake = FakeHelpers()
        assert fake.rgb_to_number([255, 0, 0]) == 16711680  # 0xFF0000

    def test_green_list(self) -> None:
        fake = FakeHelpers()
        assert fake.rgb_to_number([0, 255, 0]) == 65280  # 0x00FF00

    def test_blue_list(self) -> None:
        fake = FakeHelpers()
        assert fake.rgb_to_number([0, 0, 255]) == 255  # 0x0000FF

    def test_dict_input(self) -> None:
        fake = FakeHelpers()
        expected = (128 << 16) | (64 << 8) | 32
        assert fake.rgb_to_number({"r": 128, "g": 64, "b": 32}) == expected

    def test_invalid_input_raises_value_error(self) -> None:
        fake = FakeHelpers()
        with pytest.raises(ValueError, match="Invalid RGB"):
            fake.rgb_to_number("not-rgb")  # type: ignore[arg-type]


# ===========================================================================
# TestNumberToRgbLinear
# ===========================================================================
class TestNumberToRgbLinear:
    def test_zero_is_red(self) -> None:
        fake = FakeHelpers()
        result = fake.number_to_rgb_linear(0, 100)
        assert result == {"r": 255, "g": 0, "b": 0}

    def test_max_is_green(self) -> None:
        fake = FakeHelpers()
        result = fake.number_to_rgb_linear(100, 100)
        assert result == {"r": 0, "g": 255, "b": 0}

    def test_max_value_zero_raises(self) -> None:
        fake = FakeHelpers()
        with pytest.raises(ValueError, match="max_value must be > 0"):
            fake.number_to_rgb_linear(50, 0)


# ===========================================================================
# TestUpsertDevice
# ===========================================================================
class TestUpsertDevice:
    def test_new_device_returns_true(self) -> None:
        fake = FakeHelpers()
        result = fake.upsert_device("DEV001", component={"name": "Test Light"})
        assert result is True
        assert "DEV001" in fake.devices

    def test_same_data_returns_false(self) -> None:
        fake = FakeHelpers()
        fake.upsert_device("DEV001", component={"name": "Test Light"})
        result = fake.upsert_device("DEV001", component={"name": "Test Light"})
        assert result is False

    def test_upsert_state_merges_nested(self) -> None:
        fake = FakeHelpers()
        fake.upsert_state("DEV001", light={"state": "ON"})
        fake.upsert_state("DEV001", light={"brightness": 100})
        assert fake.states["DEV001"]["light"]["state"] == "ON"
        assert fake.states["DEV001"]["light"]["brightness"] == 100


# ===========================================================================
# TestHandleSignal
# ===========================================================================
class TestHandleSignal:
    def test_signal_sets_running_false(self) -> None:
        fake = FakeHelpers()
        assert fake.running is True
        fake._handle_signal(signal.SIGTERM)
        assert fake.running is False

    def test_signal_logs_warning(self) -> None:
        fake = FakeHelpers()
        fake._handle_signal(signal.SIGINT)
        fake.logger.warning.assert_called()
        call_args = fake.logger.warning.call_args[0][0]
        assert "SIGINT" in call_args
