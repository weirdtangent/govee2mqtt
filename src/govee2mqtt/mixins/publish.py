# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import json

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class PublishMixin:

    # Service -------------------------------------------------------------------------------------

    async def publish_service_discovery(self: Govee2Mqtt) -> None:
        device_id = "service"

        device = {
            "platform": "mqtt",
            "stat_t": self.mqtt_helper.stat_t(device_id, "service"),
            "cmd_t": self.mqtt_helper.cmd_t(device_id),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device": {
                "name": self.service_name,
                "identifiers": [
                    self.mqtt_helper.service_slug,
                ],
                "manufacturer": "weirdTangent",
                "sw_version": self.config["version"],
            },
            "origin": {
                "name": self.service_name,
                "sw_version": self.config["version"],
                "support_url": "https://github.com/weirdtangent/govee2mqtt",
            },
            "qos": self.qos,
            "cmps": {
                "server": {
                    "platform": "binary_sensor",
                    "name": self.service_name,
                    "uniq_id": self.mqtt_helper.svc_unique_id("server"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "server"),
                    "payload_on": "online",
                    "payload_off": "offline",
                    "device_class": "connectivity",
                    "entity_category": "diagnostic",
                    "icon": "mdi:server",
                },
                "api_calls": {
                    "platform": "sensor",
                    "name": "API calls today",
                    "uniq_id": self.mqtt_helper.svc_unique_id("api_calls"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "api_calls"),
                    "unit_of_measurement": "calls",
                    "entity_category": "diagnostic",
                    "state_class": "total_increasing",
                    "icon": "mdi:api",
                },
                "rate_limited": {
                    "platform": "binary_sensor",
                    "name": "Rate limited",
                    "uniq_id": self.mqtt_helper.svc_unique_id("rate_limited"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "rate_limited"),
                    "payload_on": "YES",
                    "payload_off": "NO",
                    "device_class": "problem",
                    "entity_category": "diagnostic",
                    "icon": "mdi:speedometer-slow",
                },
                "refresh_interval": {
                    "platform": "number",
                    "name": "Refresh Interval",
                    "uniq_id": f"{self.mqtt_helper.service_slug}_refresh_interval",
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "refresh_interval"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "refresh_interval"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 3600,
                    "step": 1,
                    "icon": "mdi:timer-refresh",
                    "mode": "box",
                },
                "rescan_interval": {
                    "platform": "number",
                    "name": "Rescan Interval",
                    "uniq_id": f"{self.mqtt_helper.service_slug}_rescan_interval",
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "rescan_interval"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "rescan_interval"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 3600,
                    "step": 1,
                    "icon": "mdi:timer-refresh",
                    "mode": "box",
                },
                "boost_interval": {
                    "platform": "number",
                    "name": "Boost Interval",
                    "uniq_id": f"{self.mqtt_helper.service_slug}_boost_interval",
                    "stat_t": self.mqtt_helper.stat_t("service", "service", "boost_interval"),
                    "cmd_t": self.mqtt_helper.cmd_t("service", "boost_interval"),
                    "unit_of_measurement": "s",
                    "min": 1,
                    "max": 30,
                    "step": 1,
                    "icon": "mdi:lightning-bolt",
                    "mode": "box",
                },
            }
        }

        topic = self.mqtt_helper.disc_t("device", device_id)
        payload = {k: v for k, v in device.items() if k != "platform"}
        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(payload), retain=True)
        self.upsert_state(device_id, internal={"discovered": True})

        self.logger.debug(f"discovery published for {self.service} ({self.mqtt_helper.service_slug})")

    async def publish_service_availability(self: Govee2Mqtt, status: str = "online") -> None:
        await asyncio.to_thread(self.mqtt_helper.safe_publish, self.mqtt_helper.avty_t("service"), status, qos=self.qos, retain=True)

    async def publish_service_state(self: Govee2Mqtt) -> None:
        service = {
            "api_calls": self.get_api_calls(),
            "last_api_call": str(self.last_call_date),
            "rate_limited": "YES" if self.is_rate_limited() else "NO",
            "refresh_interval": self.device_interval,
            "rescan_interval": self.device_list_interval,
            "boost_interval": self.device_boost_interval,
        }

        for key, value in service.items():
            await asyncio.to_thread(
                self.mqtt_helper.safe_publish,
                self.mqtt_helper.stat_t("service", "service", key),
                json.dumps(value) if isinstance(value, dict) else value,
                qos=self.mqtt_config["qos"],
                retain=True,
            )

    # Devices -------------------------------------------------------------------------------------

    async def publish_device_discovery(self: Govee2Mqtt, device_id: str) -> None:
        component = self.get_component(device_id)
        for slug, mode in self.get_modes(device_id).items():
            component["cmps"][f"{device_id}_{slug}"] = mode

        topic = self.mqtt_helper.disc_t("device", device_id)
        payload = {k: v for k, v in component.items() if k != "platform"}
        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(payload), retain=True)
        self.upsert_state(device_id, internal={"discovered": True})

    async def publish_device_availability(self: Govee2Mqtt, device_id: str, online: bool = True) -> None:
        payload = "online" if online else "offline"

        avty_t = self.get_device_availability_topic(device_id)
        await asyncio.to_thread(self.mqtt_helper.safe_publish, avty_t, payload, retain=True)

    async def publish_device_state(self: Govee2Mqtt, device_id: str, subject: str = "", sub: str = "") -> None:
        if not self.is_discovered(device_id):
            self.logger.debug(f"discovery not complete for {device_id} yet, holding off on sending state")
            return

        for state, value in self.states[device_id].items():
            if subject and state != subject:
                continue
            if isinstance(value, dict):
                for k, v in value.items():
                    if sub and k != sub:
                        continue
                    topic = self.mqtt_helper.stat_t(device_id, state, k)
                    if isinstance(v, list):
                        v = json.dumps(v)
                    await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, v, retain=True)
            else:
                topic = self.mqtt_helper.stat_t(device_id, state)
                await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, value, retain=True)
