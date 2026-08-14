# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
"""Tests for clearing/rebuilding HA discovery when the entity layout changes."""

import re
import pytest
from unittest.mock import AsyncMock, MagicMock

from govee2mqtt.mixins.helpers import HelpersMixin
from govee2mqtt.mixins.mqtt import MqttMixin
from govee2mqtt.mixins.publish import PublishMixin


class FakeService(HelpersMixin, PublishMixin, MqttMixin):
    def __init__(self, devices=None):
        self.logger = MagicMock()
        self.mqtt_config = {"discovery_prefix": "homeassistant"}
        self.mqtt_helper = MagicMock()
        self.mqtt_helper.service_slug = "govee2mqtt"
        self.mqtt_helper.obj_id = MagicMock(side_effect=lambda dev, e="": re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", f"{dev} {e}".lower())).strip("_"))
        self.mqtt_helper.disc_t = MagicMock(side_effect=lambda kind, did: f"homeassistant/{kind}/govee2mqtt_{did}/config")
        self.devices = {d: {"component": {}} for d in (devices or [])}
        self.states = {d: {"internal": {"discovered": True}} for d in (devices or [])}
        self.publish_service_state = AsyncMock()

    def upsert_state(self, device_id, **kwargs):
        for section, values in kwargs.items():
            self.states.setdefault(device_id, {}).setdefault(section, {}).update(values)
        return True


def _cleared_topics(svc):
    return [c.args[0] for c in svc.mqtt_helper.safe_publish.call_args_list if c.args[1] == ""]


class TestClearDiscovery:
    @pytest.mark.asyncio
    async def test_delegates_to_the_broker_sweep(self):
        """The device map is empty at connect time, so the topic list must come from the broker."""
        svc = FakeService()
        svc.clear_retained_discovery = AsyncMock()

        await svc.clear_discovery()

        svc.clear_retained_discovery.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clears_topics_the_device_map_never_knew_about(self):
        svc = FakeService()  # no devices loaded yet, exactly as at mqtt_on_connect
        svc.collect_retained_discovery_topics = AsyncMock(
            return_value=[
                "homeassistant/device/govee2mqtt_AA:BB/config",
                "homeassistant/device/govee2mqtt_service/config",
            ]
        )

        await svc.clear_discovery()

        assert _cleared_topics(svc) == [
            "homeassistant/device/govee2mqtt_AA:BB/config",
            "homeassistant/device/govee2mqtt_service/config",
        ]

    @pytest.mark.asyncio
    async def test_clears_with_empty_payload_retained(self):
        """An empty payload removes the registry entry; None would publish the string "null"."""
        svc = FakeService()
        svc.collect_retained_discovery_topics = AsyncMock(return_value=["homeassistant/device/govee2mqtt_service/config"])

        await svc.clear_discovery()

        for c in svc.mqtt_helper.safe_publish.call_args_list:
            assert c.args[1] == ""
            assert c.kwargs == {"retain": True}

    @pytest.mark.asyncio
    async def test_marks_loaded_devices_undiscovered(self):
        """Matters on the manual reset path, where devices are loaded by the time it runs."""
        svc = FakeService(devices=["AA:BB"])
        svc.clear_retained_discovery = AsyncMock()

        await svc.clear_discovery()

        assert svc.states["AA:BB"]["internal"]["discovered"] is False


class TestResetDiscoveryCommand:
    @pytest.mark.asyncio
    async def test_reset_discovery_is_dispatched(self):
        svc = FakeService()
        svc.reset_discovery = AsyncMock()

        await svc.handle_service_command("reset_discovery", "PRESS")

        svc.reset_discovery.assert_awaited_once()
        svc.logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_discovery_does_not_republish_service_state(self):
        """reset_discovery returns early; rediscover_all already republishes state."""
        svc = FakeService()
        svc.reset_discovery = AsyncMock()

        await svc.handle_service_command("reset_discovery", "PRESS")

        svc.publish_service_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_numeric_commands_still_work(self):
        svc = FakeService()

        await svc.handle_service_command("refresh_interval", "45")

        assert svc.device_interval == 45
        svc.publish_service_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_command_still_rejected(self):
        svc = FakeService()

        await svc.handle_service_command("nonsense", "1")

        svc.logger.error.assert_called_once()
        svc.publish_service_state.assert_not_awaited()


class TestSchemaVersion:
    def test_service_declares_a_schema_version(self):
        assert MqttMixin.DISCOVERY_SCHEMA_VERSION >= 1

    def test_version_topic_is_outside_the_command_wildcard(self):
        """`<slug>/service/+/set` must not swallow the version topic."""
        svc = FakeService()

        topic = svc.discovery_schema_version_topic()

        assert topic == "govee2mqtt/service/discovery_schema_version"
        assert not topic.endswith("/set")
        assert len(topic.split("/")) == 3
