# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mqtt_helper import MqttHelper

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

    # ---- kettles (H717x) ----
    def test_h7170_is_kettle(self) -> None:
        assert self._classify("H7170") == "kettle"

    def test_h7171_is_kettle(self) -> None:
        assert self._classify("H7171") == "kettle"

    # ---- sensors (H5xxx) ----
    def test_h5074_is_sensor(self) -> None:
        assert self._classify("H5074") == "sensor"

    def test_h5179_is_sensor(self) -> None:
        assert self._classify("H5179") == "sensor"

    # ---- device groups (virtual, no real model number) ----
    def test_same_mode_group_is_group(self) -> None:
        assert self._classify("SameModeGroup") == "group"

    def test_base_group_is_group(self) -> None:
        assert self._classify("BaseGroup") == "group"

    def test_group_logs_no_warning(self) -> None:
        fake = FakeGovee()
        fake.classify_device({"sku": "SameModeGroup", "deviceName": "Lanterns", "device": "6029841"})
        fake.logger.warning.assert_not_called()

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


# ===========================================================================
# TestBuildSensorDiscoveryTopics
# ===========================================================================
class TestBuildSensorDiscoveryTopics:
    """Regression test for issue #78: discovery state_topic / availability_topic
    for temperature & humidity sensors must match the topics the values are
    actually published to (device_id-scoped, with the sub-part), otherwise the
    entities stay `unavailable` in Home Assistant.
    """

    def _make_fake(self) -> "FakeGovee":
        fake = FakeGovee()
        fake.service = "govee"
        fake.service_name = "govee service"
        fake.qos = 0
        fake.config = {"version": "v2.8.1"}
        fake.states = {}
        fake.mqtt_helper = MqttHelper("govee", default_qos=0, default_retain=True)
        fake.upsert_state = MagicMock()  # type: ignore[method-assign]
        fake.prepare_device = AsyncMock()  # type: ignore[method-assign]
        return fake

    async def _build(self, instance: str) -> dict[str, Any]:
        fake = self._make_fake()
        sensor = {
            "device": "03:33:CD:ED:00:00:00:0A:FF:FF:00:13:FF:FF:00:21",
            "deviceName": "Pool Thermometer",
            "sku": "H5109",
            "capabilities": [{"instance": instance}],
        }
        device_id = await fake.build_sensor(sensor)
        # prepare_device(device, raw_id, device_id, name) — grab the discovery payload
        device = fake.prepare_device.call_args[0][0]
        return {"device_id": device_id, "device": device, "helper": fake.mqtt_helper}

    async def test_temperature_topics_match_published_topics(self) -> None:
        result = await self._build("sensorTemperature")
        device_id = result["device_id"]
        helper: MqttHelper = result["helper"]
        device = result["device"]

        # The value is published to stat_t(device_id, "sensor", "temperature")
        # and availability to avty_t(device_id) — discovery must point there.
        expected_state = helper.stat_t(device_id, "sensor", "temperature")
        expected_avty = helper.avty_t(device_id)

        assert device["stat_t"] == expected_state
        assert device["avty_t"] == expected_avty
        assert device["cmps"]["temperature"]["stat_t"] == expected_state
        # Guard against the old bug: parent-scoped topic with no sub-part.
        assert not device["stat_t"].endswith("/sensor")

    async def test_humidity_topics_match_published_topics(self) -> None:
        result = await self._build("sensorHumidity")
        device_id = result["device_id"]
        helper: MqttHelper = result["helper"]
        device = result["device"]

        expected_state = helper.stat_t(device_id, "sensor", "humidity")
        expected_avty = helper.avty_t(device_id)

        assert device["stat_t"] == expected_state
        assert device["avty_t"] == expected_avty
        assert device["cmps"]["humidity"]["stat_t"] == expected_state
        assert not device["stat_t"].endswith("/sensor")


# ===========================================================================
# TestPrepareDeviceLogging
# ===========================================================================
class TestPrepareDeviceLogging:
    """The 'added new ...' line is the only startup record of what the service
    adopted, so it has to carry the Govee device id. That id is MAC-derived,
    which makes it the one field that ties a device back to a client seen on
    the network.
    """

    def _make_fake(self) -> "FakeGovee":
        fake = FakeGovee()
        fake.states = {"AABBCCDDEEFF": {"internal": {}}}
        fake.upsert_device = MagicMock()  # type: ignore[method-assign]
        fake.upsert_state = MagicMock()  # type: ignore[method-assign]
        fake.build_device_states = AsyncMock()  # type: ignore[method-assign]
        fake.is_discovered = MagicMock(return_value=False)  # type: ignore[method-assign]
        fake.get_device_name = MagicMock(return_value="Smart Kettle")  # type: ignore[method-assign]
        fake.publish_device_discovery = AsyncMock()  # type: ignore[method-assign]
        fake.publish_device_availability = AsyncMock()  # type: ignore[method-assign]
        fake.publish_device_state = AsyncMock()  # type: ignore[method-assign]
        return fake

    async def test_log_line_includes_raw_id(self) -> None:
        fake = self._make_fake()
        device = {"device": {"name": "Smart Kettle", "model": "H7170"}}

        await fake.prepare_device(device, "aa:bb:cc:dd:ee:ff", "AABBCCDDEEFF", "kettle")

        message = fake.logger.info.call_args[0][0]
        assert "id=AA:BB:CC:DD:EE:FF" in message
        assert "added new kettle" in message
        assert "H7170" in message

    async def test_no_log_line_when_already_discovered(self) -> None:
        fake = self._make_fake()
        fake.is_discovered = MagicMock(return_value=True)  # type: ignore[method-assign]
        device = {"device": {"name": "Smart Kettle", "model": "H7170"}}

        await fake.prepare_device(device, "aa:bb:cc:dd:ee:ff", "AABBCCDDEEFF", "kettle")

        fake.logger.info.assert_not_called()


# ===========================================================================
# TestBuildGroup
# ===========================================================================
class TestBuildGroup:
    """Govee device groups (BaseGroup / SameModeGroup) are virtual devices: the API takes a
    powerSwitch command for them but rejects /device/state and /device/scenes, so they are
    adopted as on/off-only lights that are never polled.
    """

    def _make_fake(self) -> "FakeGovee":
        fake = FakeGovee()
        fake.service = "govee"
        fake.service_name = "govee service"
        fake.qos = 0
        fake.config = {"version": "v2.10.3"}
        fake.states = {}
        fake.mqtt_helper = MqttHelper("govee", default_qos=0, default_retain=True)
        fake.upsert_state = MagicMock()  # type: ignore[method-assign]
        fake.prepare_device = AsyncMock()  # type: ignore[method-assign]
        fake.get_device_scenes = AsyncMock(return_value=[])  # type: ignore[method-assign]
        return fake

    def _group(self, sku: str = "SameModeGroup", name: str = "Great Room Lamps") -> dict[str, Any]:
        return {
            "sku": sku,
            "device": "5037841",
            "deviceName": name,
            "capabilities": [
                {
                    "type": "devices.capabilities.on_off",
                    "instance": "powerSwitch",
                    "parameters": {"dataType": "ENUM", "options": [{"name": "on", "value": 1}, {"name": "off", "value": 0}]},
                }
            ],
        }

    async def test_group_is_routed_to_build_group(self) -> None:
        fake = self._make_fake()
        fake.build_group = AsyncMock(return_value="5037841")  # type: ignore[method-assign]

        assert await fake.build_component(self._group()) == "5037841"
        fake.build_group.assert_awaited_once()

    async def test_builds_onoff_only_light(self) -> None:
        fake = self._make_fake()
        device_id = await fake.build_group(self._group())
        device = fake.prepare_device.call_args[0][0]
        light = device["cmps"]["light"]

        assert device_id == "5037841"
        assert list(device["cmps"]) == ["light"]
        assert light["p"] == "light"
        assert light["supported_color_modes"] == ["onoff"]
        assert light["stat_t"] == fake.mqtt_helper.stat_t(device_id, "light", "state")
        assert light["cmd_t"] == fake.mqtt_helper.cmd_t(device_id, "light")
        assert light["avty_t"] == fake.mqtt_helper.avty_t(device_id)

    async def test_group_claims_no_mac_connection(self) -> None:
        fake = self._make_fake()
        await fake.build_group(self._group())
        device = fake.prepare_device.call_args[0][0]

        # the group id is not a MAC — publishing it as one would collide in HA's device registry
        assert "connections" not in device["device"]
        assert device["device"]["model"] == "SameModeGroup"

    async def test_marks_state_as_group_and_seeds_off(self) -> None:
        fake = self._make_fake()
        await fake.build_group(self._group(sku="BaseGroup", name="Steelers"))

        internal = next(c.kwargs["internal"] for c in fake.upsert_state.call_args_list if "internal" in c.kwargs)
        assert internal["is_group"] is True
        assert internal["raw_id"] == "5037841"
        assert internal["sku"] == "BaseGroup"

        light_states = [c.kwargs["light"] for c in fake.upsert_state.call_args_list if "light" in c.kwargs]
        assert light_states == [{"state": "OFF"}]

    async def test_existing_state_is_not_reset_to_off(self) -> None:
        fake = self._make_fake()
        fake.states = {"5037841": {"light": {"state": "ON"}}}
        await fake.build_group(self._group())

        assert not [c for c in fake.upsert_state.call_args_list if "light" in c.kwargs]

    async def test_no_scene_lookup_for_groups(self) -> None:
        fake = self._make_fake()
        await fake.build_group(self._group())

        # /device/scenes answers "devices not exist" for a group — asking is a wasted API call
        fake.get_device_scenes.assert_not_awaited()
