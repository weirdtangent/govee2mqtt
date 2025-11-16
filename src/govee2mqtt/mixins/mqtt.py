# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
from typing import TYPE_CHECKING, Any

from mqtt_helper import BaseMqttMixin
from paho.mqtt.client import Client, MQTTMessage

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class MqttMixin(BaseMqttMixin):
    def mqtt_subscription_topics(self: Govee2Mqtt) -> list[str]:
        return [
            "homeassistant/status",
            f"{self.mqtt_helper.service_slug}/service/+/set",
            f"{self.mqtt_helper.service_slug}/service/+/command",
            f"{self.mqtt_helper.service_slug}/+/light/set",
            f"{self.mqtt_helper.service_slug}/+/light/+/set",
            f"{self.mqtt_helper.service_slug}/+/switch/+/set",
        ]

    async def mqtt_on_message(self: Govee2Mqtt, client: Client, userdata: Any, msg: MQTTMessage) -> None:
        topic = msg.topic
        components = topic.split("/")

        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            try:
                payload = msg.payload.decode("utf-8")
            except Exception:
                self.logger.warning("failed to decode MQTT payload: {err}")
                return None

        if components[0] == self.mqtt_config["discovery_prefix"]:
            return await self.handle_homeassistant_message(payload)

        if components[0] == self.mqtt_helper.service_slug and components[1] == "service":
            return await self.handle_service_message(components[2], payload)

        if components[0] == self.mqtt_helper.service_slug:
            return await self.handle_device_topic(components, payload)

        self.logger.debug(f"did not process message on MQTT topic: {topic} with {payload}")

    async def handle_homeassistant_message(self: Govee2Mqtt, payload: str) -> None:
        if payload == "online":
            await self.rediscover_all()
            self.logger.info("home assistant came online — rediscovering devices")

    async def handle_device_topic(self: Govee2Mqtt, components: list[str], payload: Any) -> None:
        parsed = self._parse_device_topic(components)
        if not parsed:
            return

        (vendor, device_id, attribute) = parsed
        if not vendor or not vendor.startswith(self.mqtt_helper.service_slug):
            self.logger.error(f"ignoring non-Govee device command, got vendor {vendor}")
            return
        if not device_id or not attribute:
            self.logger.error(f"failed to parse device_id and/or payload from mqtt topic components: {components}")
            return
        if not self.devices.get(device_id, None):
            self.logger.warning(f"got MQTT message for unknown device: {device_id}")
            return

        self.logger.info(f"got message for {device_id}: {payload}")
        await self.send_command(device_id, attribute, payload)

    def _parse_device_topic(self: Govee2Mqtt, components: list[str]) -> list[str | None] | None:
        """Extract (vendor, device_id, attribute) from an MQTT topic components list (underscore-delimited)."""
        try:
            if components[-1] != "set":
                return None

            # Example topics
            # govee2mqtt/govee2mqtt_2BEFD0C907BB6BF2/light/set
            # govee2mqtt/govee2mqtt_2BEFD0C907BB6BF2/light/rgb_color/set
            # govee2mqtt/govee2mqtt_2BEFD0C907BB6BF2/switch/dreamview/set

            vendor, device_id = components[1].split("_", 1)
            attribute = components[-2]

            return [vendor, device_id, attribute]

        except Exception as e:
            self.logger.warning(f"malformed device topic: {components} ({e})")
            return None

    def safe_split_device(self: Govee2Mqtt, topic: str, segment: str) -> list[str]:
        """Split a topic segment into (vendor, device_id) safely."""
        try:
            return segment.split("-", 1)
        except ValueError:
            self.logger.warning(f"ignoring malformed topic: {topic}")
            return []

    def is_discovered(self: Govee2Mqtt, device_id: str) -> bool:
        return bool(self.states.get(device_id, {}).get("internal", {}).get("discovered", False))

    def set_discovered(self: Govee2Mqtt, device_id: str) -> None:
        self.upsert_state(device_id, internal={"discovered": True})
