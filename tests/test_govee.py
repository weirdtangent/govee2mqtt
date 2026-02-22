# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from typing import Any
from unittest.mock import MagicMock

from govee2mqtt.mixins.govee import GoveeMixin


# ---------------------------------------------------------------------------
# Fake class that composes GoveeMixin with the minimal attributes it needs
# ---------------------------------------------------------------------------
class FakeGovee(GoveeMixin):
    def __init__(self) -> None:
        self.logger = MagicMock()
        self.devices: dict[str, Any] = {}
        self.discovery_complete = False


# ===========================================================================
# TestClassifyDevice
# ===========================================================================
class TestClassifyDevice:
    """Verify SKU_CLASS_PATTERNS correctly classify Govee device SKUs."""

    def _classify(self, sku: str) -> str:
        fake = FakeGovee()
        return fake.classify_device({"sku": sku, "deviceName": "Test", "device": "AA:BB:CC:DD:EE:FF"})

    # ---- lights (H6xxx, H7xxx except H710x/H712x/H714x/H715x/H716x, H8xxx) ----
    def test_h6141_is_light(self) -> None:
        assert self._classify("H6141") == "light"

    def test_h7060_is_light(self) -> None:
        assert self._classify("H7060") == "light"

    def test_h6042_is_light(self) -> None:
        assert self._classify("H6042") == "light"

    def test_h8071_is_light(self) -> None:
        assert self._classify("H8071") == "light"

    # ---- fans (H710x) ----
    def test_h7100_is_fan(self) -> None:
        assert self._classify("H7100") == "fan"

    def test_h7101_is_fan(self) -> None:
        assert self._classify("H7101") == "fan"

    # ---- air purifiers (H712x) ----
    def test_h7120_is_air_purifier(self) -> None:
        assert self._classify("H7120") == "air_purifier"

    def test_h7122_is_air_purifier(self) -> None:
        assert self._classify("H7122") == "air_purifier"

    # ---- humidifiers (H714x) ----
    def test_h7140_is_humidifier(self) -> None:
        assert self._classify("H7140") == "humidifier"

    def test_h7141_is_humidifier(self) -> None:
        assert self._classify("H7141") == "humidifier"

    # ---- dehumidifiers (H715x) ----
    def test_h7150_is_dehumidifier(self) -> None:
        assert self._classify("H7150") == "dehumidifier"

    # ---- aroma diffusers (H716x) ----
    def test_h7160_is_aroma_diffuser(self) -> None:
        assert self._classify("H7160") == "aroma_diffuser"

    # ---- sensors (H5xxx) ----
    def test_h5074_is_sensor(self) -> None:
        assert self._classify("H5074") == "sensor"

    def test_h5179_is_sensor(self) -> None:
        assert self._classify("H5179") == "sensor"

    # ---- unknown / unsupported ----
    def test_unknown_sku_returns_empty(self) -> None:
        assert self._classify("ZZZZ") == ""

    def test_unknown_prefix_returns_empty(self) -> None:
        assert self._classify("A1234") == ""

    def test_unknown_logs_warning_before_discovery(self) -> None:
        fake = FakeGovee()
        fake.discovery_complete = False
        fake.classify_device({"sku": "ZZZZ", "deviceName": "Mystery", "device": "00:00:00:00:00:00"})
        fake.logger.warning.assert_called_once()
        assert "ZZZZ" in fake.logger.warning.call_args[0][0]

    def test_unknown_no_warning_after_discovery(self) -> None:
        fake = FakeGovee()
        fake.discovery_complete = True
        fake.classify_device({"sku": "ZZZZ", "deviceName": "Mystery", "device": "00:00:00:00:00:00"})
        fake.logger.warning.assert_not_called()
