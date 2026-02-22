# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mqtt_helper import BaseMqttMixin, decode_mqtt_payload, parse_device_topic
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
            f"{self.mqtt_helper.service_slug}/+/select/+/set",
            f"{self.mqtt_helper.service_slug}/+/number/+/set",
        ]

    async def mqtt_on_message(self: Govee2Mqtt, client: Client, userdata: Any, msg: MQTTMessage) -> None:
        topic = msg.topic
        components = topic.split("/")

        payload = decode_mqtt_payload(msg.payload)
        if payload is None:
            return None

        if components[0] == self.mqtt_config["discovery_prefix"]:
            return await self.handle_homeassistant_message(payload)

        if components[0] == self.mqtt_helper.service_slug and components[1] == "service":
            return await self.handle_service_command(components[2], payload)

        if components[0] == self.mqtt_helper.service_slug:
            return await self.handle_device_topic(components, payload)

        self.logger.debug(f"did not process message on mqtt topic: {topic} with {payload}")

    async def handle_homeassistant_message(self: Govee2Mqtt, payload: str) -> None:
        if payload == "online":
            await self.rediscover_all()
            self.logger.info("home Assistant came online — rediscovering devices")

    async def handle_device_topic(self: Govee2Mqtt, components: list[str], payload: Any) -> None:
        parsed = parse_device_topic(components)
        if not parsed:
            return

        vendor, device_id, attribute = parsed
        if not vendor or not vendor.startswith(self.mqtt_helper.service_slug):
            self.logger.error(f"ignoring non-Govee device command, got vendor {vendor}")
            return
        if not device_id or not attribute:
            self.logger.error(f"failed to parse device_id and/or payload from mqtt topic components: {components}")
            return
        if not self.devices.get(device_id, None):
            self.logger.warning(f"got mqtt message for unknown device: ({device_id})")
            return

        self.logger.info(f"got message for '{self.get_device_name(device_id)}': {payload}")
        await self.send_command(device_id, attribute, payload)

    def is_discovered(self: Govee2Mqtt, device_id: str) -> bool:
        return bool(self.states.get(device_id, {}).get("internal", {}).get("discovered", False))

    def set_discovered(self: Govee2Mqtt, device_id: str) -> None:
        self.upsert_state(device_id, internal={"discovered": True})
