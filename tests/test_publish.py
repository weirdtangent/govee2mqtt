# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import pytest
from unittest.mock import MagicMock, patch

from govee2mqtt.mixins.publish import PublishMixin
from govee2mqtt.mixins.helpers import HelpersMixin


class FakePublisher(HelpersMixin, PublishMixin):
    def __init__(self):
        self.service = "govee2mqtt"
        self.service_name = "govee2mqtt service"
        self.qos = 0
        self.config = {"version": "v0.1.0-test"}
        self.logger = MagicMock()
        self.mqtt_helper = MagicMock()
        self.mqtt_helper.safe_publish = MagicMock()
        self.mqtt_helper.service_slug = "govee2mqtt"
        self.mqtt_helper.svc_unique_id = MagicMock(side_effect=lambda e: f"govee2mqtt_{e}")
        self.mqtt_helper.dev_unique_id = MagicMock(side_effect=lambda d, e: f"govee2mqtt_{d}_{e}")
        self.mqtt_helper.device_slug = MagicMock(side_effect=lambda d: f"govee2mqtt_{d}")
        self.mqtt_helper.stat_t = MagicMock(side_effect=lambda *args: "/".join(["govee2mqtt"] + list(args)))
        self.mqtt_helper.avty_t = MagicMock(side_effect=lambda *args: "/".join(["govee2mqtt"] + list(args) + ["availability"]))
        self.mqtt_helper.cmd_t = MagicMock(side_effect=lambda *args: "/".join(["govee2mqtt"] + list(args) + ["set"]))
        self.mqtt_helper.disc_t = MagicMock(side_effect=lambda kind, did: f"homeassistant/{kind}/govee2mqtt_{did}/config")
        self.devices = {}
        self.states = {}


async def _fake_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


class TestServiceDiscovery:
    @pytest.mark.asyncio
    async def test_publishes_service_discovery(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        pub.mqtt_helper.safe_publish.assert_called()
        topic = pub.mqtt_helper.safe_publish.call_args_list[0].args[0]
        payload = json.loads(pub.mqtt_helper.safe_publish.call_args_list[0].args[1])

        assert topic == "homeassistant/device/govee2mqtt_service/config"
        assert payload["device"]["name"] == "govee2mqtt service"
        assert "cmps" in payload
        assert len(payload["cmps"]) == 6

    @pytest.mark.asyncio
    async def test_retain_true_on_publish(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        # Verify retain=True is passed
        call_args = pub.mqtt_helper.safe_publish.call_args
        assert call_args.kwargs.get("retain") is True or (len(call_args.args) > 2 and call_args.args[2] is True)

    @pytest.mark.asyncio
    async def test_filters_p_key_from_payload(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        payload = json.loads(pub.mqtt_helper.safe_publish.call_args_list[0].args[1])
        assert "p" not in payload

    @pytest.mark.asyncio
    async def test_marks_discovered(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_discovery()

        assert pub.states["service"]["internal"]["discovered"] is True


class TestServiceAvailability:
    @pytest.mark.asyncio
    async def test_publishes_online(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_availability("online")

        assert pub.mqtt_helper.safe_publish.call_args.args[1] == "online"

    @pytest.mark.asyncio
    async def test_publishes_offline(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_availability("offline")

        assert pub.mqtt_helper.safe_publish.call_args.args[1] == "offline"


class TestServiceState:
    @pytest.mark.asyncio
    async def test_publishes_all_metrics(self):
        from datetime import datetime

        pub = FakePublisher()
        pub.api_calls = 42
        pub.last_call_date = datetime(2026, 1, 15, 10, 30, 0)
        pub.rate_limited = False
        pub.device_interval = 30
        pub.device_list_interval = 3600
        pub.device_boost_interval = 5

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_service_state()

        topics = [c.args[0] for c in pub.mqtt_helper.safe_publish.call_args_list]
        assert any("server" in t for t in topics)
        assert any("api_calls" in t for t in topics)
        assert any("boost_interval" in t for t in topics)
        assert any("rate_limited" in t for t in topics)


class TestDeviceDiscovery:
    @pytest.mark.asyncio
    async def test_publishes_device_discovery(self):
        pub = FakePublisher()
        pub.devices["LIGHT001"] = {
            "component": {
                "device": {"name": "Bedroom Light"},
                "cmps": {"light": {"p": "light"}},
            }
        }
        pub.states["LIGHT001"] = {}

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_discovery("LIGHT001")

        topic = pub.mqtt_helper.safe_publish.call_args.args[0]
        assert topic == "homeassistant/device/govee2mqtt_LIGHT001/config"

    @pytest.mark.asyncio
    async def test_retain_true(self):
        pub = FakePublisher()
        pub.devices["LIGHT001"] = {"component": {"device": {"name": "Bedroom Light"}}}
        pub.states["LIGHT001"] = {}

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_discovery("LIGHT001")

        call_args = pub.mqtt_helper.safe_publish.call_args
        assert call_args.kwargs.get("retain") is True or (len(call_args.args) > 2 and call_args.args[2] is True)

    @pytest.mark.asyncio
    async def test_marks_discovered(self):
        pub = FakePublisher()
        pub.devices["LIGHT001"] = {"component": {"device": {"name": "Bedroom Light"}}}
        pub.states["LIGHT001"] = {}

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_discovery("LIGHT001")

        assert pub.states["LIGHT001"]["internal"]["discovered"] is True


class TestDeviceAvailability:
    @pytest.mark.asyncio
    async def test_retain_true(self):
        pub = FakePublisher()

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_availability("LIGHT001", online=True)

        call_args = pub.mqtt_helper.safe_publish.call_args
        assert call_args.kwargs.get("retain") is True or (len(call_args.args) > 2 and call_args.args[2] is True)


class TestDeviceState:
    @pytest.mark.asyncio
    async def test_skips_internal_key(self):
        pub = FakePublisher()
        pub.states["LIGHT001"] = {
            "internal": {"discovered": True, "raw_id": "abc"},
            "light": {"state": "ON"},
        }

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("LIGHT001")

        topics = [c.args[0] for c in pub.mqtt_helper.safe_publish.call_args_list]
        assert not any("internal" in t for t in topics)
        assert any("light" in t for t in topics)

    @pytest.mark.asyncio
    async def test_rgb_color_comma_conversion(self):
        pub = FakePublisher()
        pub.states["LIGHT001"] = {
            "light": {"rgb_color": [255, 128, 0]},
        }

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("LIGHT001")

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "rgb_color" in c.args[0]:
                assert c.args[1] == "255,128,0"
                break
        else:
            pytest.fail("rgb_color not published")

    @pytest.mark.asyncio
    async def test_retain_true_on_dict_values(self):
        pub = FakePublisher()
        pub.states["LIGHT001"] = {
            "light": {"state": "ON"},
        }

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("LIGHT001")

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "light" in c.args[0]:
                assert c.kwargs.get("retain") is True or (len(c.args) > 2 and c.args[2] is True)
                break

    @pytest.mark.asyncio
    async def test_list_values_encoded_as_json(self):
        pub = FakePublisher()
        pub.states["LIGHT001"] = {
            "sensor": {"items": [1, 2, 3]},
        }

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("LIGHT001")

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "items" in c.args[0]:
                assert c.args[1] == json.dumps([1, 2, 3])
                break

    @pytest.mark.asyncio
    async def test_attributes_published_as_json(self):
        pub = FakePublisher()
        pub.states["LIGHT001"] = {
            "attributes": {"firmware": "v1.0", "model": "H6061"},
        }

        with patch("govee2mqtt.mixins.publish.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _fake_to_thread
            await pub.publish_device_state("LIGHT001")

        for c in pub.mqtt_helper.safe_publish.call_args_list:
            if "attributes" in c.args[0]:
                payload = json.loads(c.args[1])
                assert payload["firmware"] == "v1.0"
                break
        else:
            pytest.fail("attributes not published")
