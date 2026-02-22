# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from govee2mqtt.mixins.mqtt import MqttMixin


# ---------------------------------------------------------------------------
# Helper to create a minimal MQTT message object
# ---------------------------------------------------------------------------
def _make_msg(topic: str, payload: Any) -> MagicMock:
    msg = MagicMock()
    msg.topic = topic
    if isinstance(payload, (dict, list)):
        msg.payload = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, str):
        msg.payload = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        msg.payload = payload
    else:
        msg.payload = str(payload).encode("utf-8")
    return msg


# ---------------------------------------------------------------------------
# Fake class that composes MqttMixin with the minimal attributes it needs
# ---------------------------------------------------------------------------
class FakeMqtt(MqttMixin):
    def __init__(self) -> None:
        self.logger = MagicMock()
        self.loop = asyncio.new_event_loop()
        self.mqtt_config: dict[str, Any] = {
            "discovery_prefix": "homeassistant",
            "host": "localhost",
            "port": 1883,
            "protocol_version": "5",
            "username": "test",
            "password": "test",
            "tls_enabled": False,
        }
        self.mqtt_helper = MagicMock()
        self.mqtt_helper.service_slug = "govee2mqtt"
        self.mqtt_connect_time = None
        self.client_id = "test-client"
        self.running = True
        self.mqttc = MagicMock()
        self.devices: dict[str, Any] = {}
        self.states: dict[str, Any] = {}

        # Async handler stubs
        self.handle_homeassistant_message = AsyncMock()
        self.handle_device_topic = AsyncMock()
        self.handle_service_command = AsyncMock()

    def close(self) -> None:
        self.loop.close()


# ===========================================================================
# TestMqttOnMessage
# ===========================================================================
class TestMqttOnMessage:
    @pytest.mark.asyncio
    async def test_ha_online_routes_to_homeassistant_handler(self) -> None:
        fake = FakeMqtt()
        msg = _make_msg("homeassistant/status", "online")
        await fake.mqtt_on_message(MagicMock(), None, msg)
        fake.handle_homeassistant_message.assert_awaited_once_with("online")
        fake.close()

    @pytest.mark.asyncio
    async def test_device_topic_routes_to_device_handler(self) -> None:
        fake = FakeMqtt()
        msg = _make_msg("govee2mqtt/govee2mqtt_DEVICEID123/light/rgb_color/set", json.dumps([255, 0, 0]))
        await fake.mqtt_on_message(MagicMock(), None, msg)
        fake.handle_device_topic.assert_awaited_once()
        fake.close()

    @pytest.mark.asyncio
    async def test_service_topic_routes_to_service_handler(self) -> None:
        fake = FakeMqtt()
        msg = _make_msg("govee2mqtt/service/refresh_interval/set", "60")
        await fake.mqtt_on_message(MagicMock(), None, msg)
        # json.loads("60") returns int 60, not the string "60"
        fake.handle_service_command.assert_awaited_once_with("refresh_interval", 60)
        fake.close()


# ===========================================================================
# TestParseDeviceTopic
# ===========================================================================
class TestParseDeviceTopic:
    def test_light_rgb_color_topic(self) -> None:
        fake = FakeMqtt()
        components = "govee2mqtt/govee2mqtt_DEVICEID123/light/rgb_color/set".split("/")
        result = fake._parse_device_topic(components)
        assert result is not None
        assert result[0] == "govee2mqtt"
        assert result[1] == "DEVICEID123"
        assert result[2] == "rgb_color"
        fake.close()

    def test_switch_dreamview_topic(self) -> None:
        fake = FakeMqtt()
        components = "govee2mqtt/govee2mqtt_DEVICEID123/switch/dreamview/set".split("/")
        result = fake._parse_device_topic(components)
        assert result is not None
        assert result[0] == "govee2mqtt"
        assert result[1] == "DEVICEID123"
        assert result[2] == "dreamview"
        fake.close()

    def test_non_set_returns_none(self) -> None:
        fake = FakeMqtt()
        components = "govee2mqtt/govee2mqtt_DEVICEID123/light/rgb_color/get".split("/")
        result = fake._parse_device_topic(components)
        assert result is None
        fake.close()

    def test_simple_light_set_topic(self) -> None:
        fake = FakeMqtt()
        components = "govee2mqtt/govee2mqtt_DEVICEID123/light/set".split("/")
        result = fake._parse_device_topic(components)
        assert result is not None
        assert result[0] == "govee2mqtt"
        assert result[1] == "DEVICEID123"
        assert result[2] == "light"
        fake.close()


# ===========================================================================
# TestHandleHomeassistantMessage
# ===========================================================================
class TestHandleHomeassistantMessage:
    @pytest.mark.asyncio
    async def test_online_calls_rediscover_all(self) -> None:
        """When HA sends 'online', rediscover_all must be called."""
        fake = FakeMqtt()
        # Replace the mocked handler with the real implementation for this test
        del fake.handle_homeassistant_message
        fake.rediscover_all = AsyncMock()
        await MqttMixin.handle_homeassistant_message(fake, "online")  # type: ignore[arg-type]
        fake.rediscover_all.assert_awaited_once()
        fake.close()

    @pytest.mark.asyncio
    async def test_offline_does_not_call_rediscover(self) -> None:
        """When HA sends 'offline', rediscover_all must NOT be called."""
        fake = FakeMqtt()
        del fake.handle_homeassistant_message
        fake.rediscover_all = AsyncMock()
        await MqttMixin.handle_homeassistant_message(fake, "offline")  # type: ignore[arg-type]
        fake.rediscover_all.assert_not_awaited()
        fake.close()


# ===========================================================================
# TestIsDiscovered
# ===========================================================================
class TestIsDiscovered:
    def test_returns_false_when_no_state(self) -> None:
        fake = FakeMqtt()
        assert fake.is_discovered("UNKNOWN_DEV") is False
        fake.close()

    def test_returns_true_after_set_discovered(self) -> None:
        fake = FakeMqtt()
        # set_discovered calls upsert_state — we need a real implementation for that
        fake.upsert_state = MagicMock(
            side_effect=lambda device_id, **kwargs: fake.states.update({device_id: _deep_merge(fake.states.get(device_id, {}), kwargs)})
        )
        fake.set_discovered("DEV001")
        assert fake.is_discovered("DEV001") is True
        fake.close()


# ---------------------------------------------------------------------------
# Minimal deep-merge helper for test (mirrors what deepmerge.Merger does)
# ---------------------------------------------------------------------------
def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
