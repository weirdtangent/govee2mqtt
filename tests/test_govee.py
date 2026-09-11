# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mqtt_helper import MqttHelper

from govee2mqtt.mixins.govee import GoveeMixin
from govee2mqtt.mixins.helpers import HelpersMixin


# ---------------------------------------------------------------------------
# Fake class that composes GoveeMixin with the minimal attributes it needs
# ---------------------------------------------------------------------------
class FakeGovee(GoveeMixin):
    def __init__(self) -> None:
        self.logger = MagicMock()
        self.devices: dict[str, Any] = {}
        self.discovery_complete = False


class FakeLightService(HelpersMixin, GoveeMixin):
    """Composes the real HelpersMixin so upsert_state actually stores state -- the cache under test
    is written by build_light_components and read back by get_light_scenes."""

    def __init__(self) -> None:
        self.logger = MagicMock()
        self.service = "govee2mqtt"
        self.service_name = "govee2mqtt service"
        self.qos = 0
        self.config = {"version": "v0.0.0-test"}
        self.devices: dict[str, Any] = {}
        self.states: dict[str, Any] = {}
        self.discovery_complete = False
        self.mqtt_helper = MqttHelper("govee2mqtt", default_qos=0, default_retain=True)


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
        reading = 72.5 if instance == "sensorTemperature" else 48.0
        fake.get_device = AsyncMock(return_value={"online": True, instance: reading})  # type: ignore[method-assign]
        sensor = {
            "device": "03:33:CD:ED:00:00:00:0A:FF:FF:00:13:FF:FF:00:21",
            "deviceName": "Pool Thermometer",
            "sku": "H5109",
            "capabilities": [{"instance": instance}],
        }
        adopted = await fake.build_sensor(sensor)
        # prepare_device(device, raw_id, device_id, name) — grab the discovery payload
        device = fake.prepare_device.call_args[0][0]
        return {"device_id": adopted[0], "device": device, "helper": fake.mqtt_helper}

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

        assert await fake.build_component(self._group()) == ["5037841"]
        fake.build_group.assert_awaited_once()

    async def test_builds_onoff_only_light(self) -> None:
        fake = self._make_fake()
        device_id = await fake.build_group(self._group())
        device = fake.prepare_device.call_args[0][0]
        group = device["cmps"]["group"]

        assert device_id == "5037841"
        assert list(device["cmps"]) == ["group"]
        assert group["p"] == "light"
        assert group["supported_color_modes"] == ["onoff"]
        assert group["stat_t"] == fake.mqtt_helper.stat_t(device_id, "light", "state")
        assert group["cmd_t"] == fake.mqtt_helper.cmd_t(device_id, "light")
        assert group["avty_t"] == fake.mqtt_helper.avty_t(device_id)

    async def test_entity_id_says_group_so_it_cannot_collide_with_a_real_light(self) -> None:
        """A Govee group called "Bedroom" must not contest light.bedroom_light with the Bedroom
        ceiling light -- HA hands the loser a _2 suffix, permanently."""
        fake = self._make_fake()
        device_id = await fake.build_group(self._group(name="Bedroom"))
        group = fake.prepare_device.call_args[0][0]["cmps"]["group"]

        assert group["obj_id"] == "bedroom_group"
        assert group["uniq_id"] == fake.mqtt_helper.dev_unique_id(device_id, "group")
        assert group["name"] == "Group"

    async def test_a_group_is_onoff_only_whatever_it_contains(self) -> None:
        """The API payload for a group of humidifiers is identical in shape to one of lamps, so the
        light domain is an assumption resting on Govee refusing to group non-lights. Keep the entity
        to the one capability a group actually has, so the assumption costs nothing if it breaks."""
        fake = self._make_fake()
        await fake.build_group(self._group(name="Humidifiers"))
        group = fake.prepare_device.call_args[0][0]["cmps"]["group"]

        assert group["supported_color_modes"] == ["onoff"]
        assert "brightness_command_topic" not in group
        assert "rgb_command_topic" not in group
        assert group["obj_id"] == "humidifiers_group"

    async def test_the_published_entity_id_is_light_bedroom_group(self) -> None:
        """obj_id alone proves nothing: HA 2026.4 ignores it and reads def_ent_id, which
        publish_device_discovery derives via apply_default_entity_ids. Assert what is actually
        published, or this passes while the real entity_id still collides with the ceiling light."""
        fake = self._make_fake()
        await fake.build_group(self._group(name="Bedroom"))
        payload = fake.prepare_device.call_args[0][0]

        # exactly what publish_device_discovery does to the payload before it goes on the wire
        published = MqttHelper("govee2mqtt").apply_default_entity_ids(payload)

        assert published["cmps"]["group"]["def_ent_id"] == "light.bedroom_group"
        assert "obj_id" not in published["cmps"]["group"]

    async def test_does_not_say_group_twice(self) -> None:
        fake = self._make_fake()
        await fake.build_group(self._group(name="Steelers Group"))
        group = fake.prepare_device.call_args[0][0]["cmps"]["group"]

        assert group["name"] is None
        assert group["obj_id"] == "steelers_group"

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


# ===========================================================================
# TestLightSceneCaching
# ===========================================================================
class TestLightSceneCaching:
    """build_light runs on every device-list refresh, so fetching scenes there costs one API call
    per light per rescan — 19 lights every 900s is ~1,800 calls/day against a 10,000/day quota,
    re-reading lists that essentially never change.
    """

    def _make_fake(self, discovery_complete: bool, cached: dict[str, Any] | None = None) -> "FakeGovee":
        fake = FakeGovee()
        fake.discovery_complete = discovery_complete
        fake.states = {"L1": {"internal": {"light_scene_values": cached}}} if cached is not None else {"L1": {"internal": {}}}
        fake.get_device_scenes = AsyncMock(return_value=[{"name": "Sunrise", "value": 1}])  # type: ignore[method-assign]
        return fake

    async def test_first_pass_after_a_restart_fetches(self) -> None:
        fake = self._make_fake(discovery_complete=False, cached={"Sunset": 9})

        scenes = await fake.get_light_scenes("L1")

        fake.get_device_scenes.assert_awaited_once()
        assert scenes == [{"name": "Sunrise", "value": 1}]

    async def test_later_rescans_reuse_the_cache(self) -> None:
        fake = self._make_fake(discovery_complete=True, cached={"Sunset": 9, "Aurora": 12})

        scenes = await fake.get_light_scenes("L1")

        fake.get_device_scenes.assert_not_awaited()
        assert scenes == [{"name": "Sunset", "value": 9}, {"name": "Aurora", "value": 12}]

    async def test_an_empty_cache_always_refetches(self) -> None:
        """A failed or rate-limited first attempt must not leave the device sceneless forever."""
        fake = self._make_fake(discovery_complete=True, cached={})

        scenes = await fake.get_light_scenes("L1")

        fake.get_device_scenes.assert_awaited_once()
        assert scenes == [{"name": "Sunrise", "value": 1}]

    async def test_an_unknown_device_refetches(self) -> None:
        fake = self._make_fake(discovery_complete=True)
        fake.states = {}

        await fake.get_light_scenes("L1")

        fake.get_device_scenes.assert_awaited_once()

    async def test_returns_the_shape_build_light_components_consumes(self) -> None:
        fake = self._make_fake(discovery_complete=True, cached={"Sunset": 9})

        scenes = await fake.get_light_scenes("L1")

        assert all(set(s) == {"name", "value"} for s in scenes)


# ===========================================================================
# TestSceneCacheEndToEnd
# ===========================================================================
class TestSceneCacheEndToEnd:
    """The unit tests above stub the cache into place, so they would all still pass if the cache
    stopped being *written* -- and the per-rescan API calls would quietly come back. This drives the
    real build_light -> build_light_components -> light_scene_values path instead.
    """

    def _make_light_service(self, scenes: list[dict[str, Any]]) -> "FakeLightService":
        fake = FakeLightService()
        fake.get_device_scenes = AsyncMock(return_value=scenes)  # type: ignore[method-assign]
        fake.prepare_device = AsyncMock()  # type: ignore[method-assign]
        return fake

    def _light(self) -> dict[str, Any]:
        return {
            "sku": "H6008",
            "device": "AA:BB:CC:DD:EE:FF",
            "deviceName": "Reading Chair",
            "capabilities": [{"instance": "powerSwitch"}, {"instance": "brightness", "parameters": {"range": {"max": 100}}}],
        }

    async def test_first_build_fetches_and_stores_the_cache(self) -> None:
        fake = self._make_light_service([{"name": "Sunset", "value": 9}, {"name": "Aurora", "value": 12}])
        fake.discovery_complete = False

        device_id = await fake.build_light(self._light())

        fake.get_device_scenes.assert_awaited_once()
        assert fake.states[device_id]["internal"]["light_scene_values"] == {"Sunset": 9, "Aurora": 12}

    async def test_a_later_rescan_neither_refetches_nor_loses_the_scene_select(self) -> None:
        fake = self._make_light_service([{"name": "Sunset", "value": 9}, {"name": "Aurora", "value": 12}])

        fake.discovery_complete = False
        await fake.build_light(self._light())
        assert fake.get_device_scenes.await_count == 1

        # the rescan the device list triggers every GOVEE_LIST_INTERVAL
        fake.discovery_complete = True
        device_id = await fake.build_light(self._light())

        assert fake.get_device_scenes.await_count == 1, "rescan re-fetched scenes"

        components = fake.prepare_device.call_args[0][0]["cmps"]
        assert "light_scene" in components, "scene select vanished on rescan"
        assert components["light_scene"]["options"] == ["Aurora", "Sunset"]
        assert fake.states[device_id]["internal"]["light_scene_values"] == {"Sunset": 9, "Aurora": 12}


# ===========================================================================
# TestSensorCapabilities
# ===========================================================================
class TestSensorCapabilities:
    """A thermo-hygrometer reports temperature AND humidity. build_sensor used to return at the
    first capability, so humidity was silently dropped — a live reading thrown away on an H5179.
    And a Bluetooth-only sensor with no gateway answers online=False with "" for everything, so
    adopting it minted entities that could never hold a value.
    """

    def _make_fake(self, readings: dict[str, Any]) -> "FakeGovee":
        fake = FakeGovee()
        fake.service = "govee2mqtt"
        fake.service_name = "govee2mqtt service"
        fake.qos = 0
        fake.config = {"version": "v0.0.0-test"}
        fake.states = {}
        fake.devices = {}
        fake.mqtt_helper = MqttHelper("govee2mqtt", default_qos=0, default_retain=True)
        fake.upsert_state = MagicMock()  # type: ignore[method-assign]
        fake.prepare_device = AsyncMock()  # type: ignore[method-assign]

        # the real get_device logs through get_device_name first; a bare AsyncMock skips that and
        # hid a KeyError that took down every sensor build in production
        async def _get_device(device_id: str) -> dict[str, Any]:
            HelpersMixin.get_device_name(fake, device_id)  # type: ignore[arg-type]
            return readings

        fake.get_device = AsyncMock(side_effect=_get_device)  # type: ignore[method-assign]
        return fake

    def _sensor(self, name: str = "Great Room H5179", sku: str = "H5179") -> dict[str, Any]:
        return {
            "device": "3A:2E:18:1F:68:12:01:03",
            "deviceName": name,
            "sku": sku,
            "capabilities": [{"instance": "sensorTemperature"}, {"instance": "sensorHumidity"}],
        }

    async def test_adopts_both_readings(self) -> None:
        fake = self._make_fake({"online": True, "sensorTemperature": 75.92, "sensorHumidity": 56.8})

        adopted = await fake.build_sensor(self._sensor())

        assert adopted == ["3A2E181F68120103_temp", "3A2E181F68120103_hmdy"]
        assert fake.prepare_device.await_count == 2

    async def test_the_humidity_entity_is_a_humidity_sensor(self) -> None:
        fake = self._make_fake({"online": True, "sensorTemperature": 75.92, "sensorHumidity": 56.8})

        await fake.build_sensor(self._sensor())

        humidity = fake.prepare_device.call_args_list[1][0][0]["cmps"]["humidity"]
        assert humidity["device_class"] == "humidity"
        assert humidity["unit_of_measurement"] == "%"
        assert humidity["obj_id"] == "great_room_h5179_humidity"

    async def test_temperature_ids_are_unchanged(self) -> None:
        """These entities already exist in installs; moving their unique_id or obj_id would strand
        them, since HA keys the registry on unique_id and never reassigns an entity_id."""
        fake = self._make_fake({"online": True, "sensorTemperature": 75.92, "sensorHumidity": 56.8})

        await fake.build_sensor(self._sensor())

        temperature = fake.prepare_device.call_args_list[0][0][0]["cmps"]["temperature"]
        assert temperature["uniq_id"] == "govee2mqtt_3A2E181F68120103temp_temperature"
        assert temperature["obj_id"] == "great_room_h5179_temperature"

    async def test_a_sensor_with_no_readings_is_not_adopted(self) -> None:
        """An H5074 with no gateway: the cloud API can see the device but never its values."""
        fake = self._make_fake({"online": False, "sensorTemperature": "", "sensorHumidity": ""})

        adopted = await fake.build_sensor(self._sensor("Bedroom H5074", "H5074"))

        assert adopted == []
        fake.prepare_device.assert_not_awaited()

    async def test_a_partly_reporting_sensor_adopts_only_what_reports(self) -> None:
        fake = self._make_fake({"online": True, "sensorTemperature": 71.0, "sensorHumidity": ""})

        adopted = await fake.build_sensor(self._sensor())

        assert adopted == ["3A2E181F68120103_temp"]

    async def test_a_zero_reading_still_counts(self) -> None:
        """0 is falsy but perfectly real — 0% humidity or 0 degrees must not read as 'no data'."""
        fake = self._make_fake({"online": True, "sensorTemperature": 0, "sensorHumidity": 0})

        adopted = await fake.build_sensor(self._sensor())

        assert len(adopted) == 2

    async def test_the_state_is_read_once_and_handed_on(self) -> None:
        """Two entities off one device must not mean two API reads, nor a third inside adoption."""
        readings = {"online": True, "sensorTemperature": 75.92, "sensorHumidity": 56.8}
        fake = self._make_fake(readings)

        await fake.build_sensor(self._sensor())

        fake.get_device.assert_awaited_once()
        assert all(call.kwargs["state"] == readings for call in fake.prepare_device.call_args_list)

    async def test_a_sensor_with_no_known_capabilities_reads_nothing(self) -> None:
        fake = self._make_fake({})
        sensor = {"device": "AA:BB", "deviceName": "Odd", "sku": "H5999", "capabilities": [{"instance": "somethingElse"}]}

        assert await fake.build_sensor(sensor) == []
        fake.get_device.assert_not_awaited()


# ===========================================================================
# TestGetDeviceName
# ===========================================================================
class TestGetDeviceName:
    """build_sensor reads a device's state before adopting it, so this is reached with nothing in
    self.devices. Raising KeyError from inside a debug log line took down every sensor build.
    """

    def _make(self) -> "FakeGovee":
        fake = FakeGovee()
        fake.devices = {}
        return fake

    def test_falls_back_to_the_id_for_an_unadopted_device(self) -> None:
        fake = self._make()

        assert HelpersMixin.get_device_name(fake, "3A2E181F68120103_temp") == "3A2E181F68120103_temp"  # type: ignore[arg-type]

    def test_returns_the_name_once_adopted(self) -> None:
        fake = self._make()
        fake.devices = {"D1": {"component": {"device": {"name": "Great Room H5179"}}}}

        assert HelpersMixin.get_device_name(fake, "D1") == "Great Room H5179"  # type: ignore[arg-type]

    def test_falls_back_when_the_payload_is_half_built(self) -> None:
        fake = self._make()
        fake.devices = {"D1": {"component": {}}}

        assert HelpersMixin.get_device_name(fake, "D1") == "D1"  # type: ignore[arg-type]
