# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
from datetime import timezone
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class PublishMixin:

    # Service -------------------------------------------------------------------------------------

    async def publish_service_discovery(self: Govee2Mqtt) -> None:
        device_id = "service"

        device = {
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
                    "p": "binary_sensor",
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
                    "p": "sensor",
                    "name": "API calls today",
                    "uniq_id": self.mqtt_helper.svc_unique_id("api_calls"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "service", "api_calls"),
                    "unit_of_measurement": "calls",
                    "entity_category": "diagnostic",
                    "state_class": "total_increasing",
                    "icon": "mdi:api",
                },
                "rate_limited": {
                    "p": "binary_sensor",
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
                    "p": "number",
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
                    "p": "number",
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
                    "p": "number",
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
            },
        }

        topic = self.mqtt_helper.disc_t("device", device_id)
        payload = {k: v for k, v in device.items() if k != "p"}
        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(payload), retain=True)
        self.upsert_state(device_id, internal={"discovered": True})

        self.logger.debug(f"discovery published for {self.service} ({self.mqtt_helper.service_slug})")

    async def publish_service_availability(self: Govee2Mqtt, status: str = "online") -> None:
        await asyncio.to_thread(self.mqtt_helper.safe_publish, self.mqtt_helper.avty_t("service"), status)

    async def publish_service_state(self: Govee2Mqtt) -> None:
        # we keep last_call_date in localtime so it rolls-over the api call counter
        # at the right time (midnight, local) but we want to send last_call_date
        # to HomeAssistant as UTC
        last_call_date = self.last_call_date
        local_tz = last_call_date.astimezone().tzinfo

        service = {
            "server": "online",
            "api_calls": self.api_calls,
            "last_api_call": last_call_date.replace(tzinfo=local_tz).astimezone(timezone.utc).isoformat(),
            "rate_limited": "YES" if self.rate_limited else "NO",
            "refresh_interval": self.device_interval,
            "rescan_interval": self.device_list_interval,
            "boost_interval": self.device_boost_interval,
        }

        for key, value in service.items():
            await asyncio.to_thread(
                self.mqtt_helper.safe_publish,
                self.mqtt_helper.stat_t("service", "service", key),
                json.dumps(value) if isinstance(value, dict) else value,
            )

    # Devices -------------------------------------------------------------------------------------

    async def publish_device_discovery(self: Govee2Mqtt, device_id: str) -> None:
        topic = self.mqtt_helper.disc_t("device", device_id)
        payload = json.dumps(self.devices[device_id]["component"])

        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, payload, retain=True)
        self.upsert_state(device_id, internal={"discovered": True})

    async def publish_device_availability(self: Govee2Mqtt, device_id: str, online: bool = True) -> None:
        topic = self.mqtt_helper.avty_t(device_id)
        payload = "online" if online else "offline"

        await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, payload, retain=True)

    async def publish_device_state(self: Govee2Mqtt, device_id: str, subject: str = "", sub: str = "") -> None:
        for state, value in self.states[device_id].items():
            if state == "internal" or (subject and state != subject):
                continue
            # Attributes need to be published as a single JSON object to the attributes topic
            if state == "attributes" and isinstance(value, dict):
                topic = self.mqtt_helper.stat_t(device_id, "attributes")
                await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, json.dumps(value), retain=True)
            # otherwise, if it's a dict, publish each key/value pair separately
            elif isinstance(value, dict):
                for k, v in value.items():
                    if sub and k != sub:
                        continue
                    topic = self.mqtt_helper.stat_t(device_id, state, k)
                    # if it's a list, convert to JSON
                    if isinstance(v, list):
                        if state == "light" and k == "rgb_color" and v:
                            try:
                                v = ",".join(str(int(channel)) for channel in v[:3])
                            except (TypeError, ValueError):
                                v = json.dumps(v)
                        else:
                            v = json.dumps(v)
                    await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, v, retain=True)
            # otherwise, publish the value as is
            else:
                topic = self.mqtt_helper.stat_t(device_id, state)
                await asyncio.to_thread(self.mqtt_helper.safe_publish, topic, value)
