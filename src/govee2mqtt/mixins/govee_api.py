# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import aiohttp
from aiohttp import ClientError
from datetime import datetime
import uuid
from zoneinfo import ZoneInfo

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt

DEVICE_URL = "https://openapi.api.govee.com/router/api/v1/device/state"
DEVICE_LIST_URL = "https://openapi.api.govee.com/router/api/v1/user/devices"
COMMAND_URL = "https://openapi.api.govee.com/router/api/v1/device/control"


class GoveeAPIMixin:
    def restore_state_values(self: Govee2Mqtt, api_calls: int, last_call_date: str) -> None:
        self.api_calls = api_calls
        self.last_call_date = datetime.strptime(last_call_date, "%Y-%m-%d %H:%M:%S.%f")

    def increase_api_calls(self: Govee2Mqtt) -> None:
        if not self.last_call_date or self.last_call_date.date() != datetime.now().date():
            self.api_calls = 0
        self.last_call_date = datetime.now()
        self.api_calls += 1

    def set_if_rate_limited(self: Govee2Mqtt, status: int) -> None:
        self.rate_limited = status == 429
        if self.rate_limited:
            self.logger.warning("request rate-limited by Govee")

    def get_headers(self: Govee2Mqtt) -> dict[str, str]:
        return {"Content-Type": "application/json", "Govee-API-Key": self.api_key}

    async def get_device_list(self: Govee2Mqtt) -> list[dict[str, Any]]:
        headers = self.get_headers()

        try:
            async with self.session.get(DEVICE_LIST_URL, headers=headers) as r:
                self.increase_api_calls()
                self.set_if_rate_limited(r.status)

                if r.status != 200:
                    self.logger.error(f"error ({r.status}) getting device list")
                    return []

                data = await r.json()

        except ClientError:
            self.logger.error("request error communicating with Govee for device list")
            return []
        except Exception:
            self.logger.error("error communicating with Govee for device list")
            return []

        result = data.get("data", [])
        if not isinstance(result, list):
            self.logger.error(f"unexpected response type from Govee: {type(result).__name__}")
            return []
        return result

    async def get_device(self: Govee2Mqtt, device_id: str, sku: str) -> dict[str, Any]:
        headers = self.get_headers()
        body = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
            },
        }

        try:
            async with self.session.post(DEVICE_URL, headers=headers, json=body) as r:
                self.increase_api_calls()
                self.set_if_rate_limited(r.status)

                if r.status != 200:
                    return {}

                data = await r.json()

        except aiohttp.ClientError as e:
            self.logger.error(f"request error communicating with Govee for device ({device_id}): {e}")
            return {}
        except Exception as e:
            self.logger.error(f"error communicating with Govee for device ({device_id}): {e}")
            return {}

        new_capabilities: dict[str, Any] = {}
        device = data.get("payload", {})

        if "capabilities" in device:
            for capability in device["capabilities"]:
                new_capabilities[capability["instance"]] = capability["state"]["value"]
            new_capabilities["lastUpdate"] = datetime.now(ZoneInfo(self.timezone))

        return new_capabilities

    async def post_command(self: Govee2Mqtt, device_id: str, sku: str, capability: dict[str, Any], instance: str, value: str) -> dict[str, Any]:
        headers = self.get_headers()
        body = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": {
                    "type": capability,
                    "instance": instance,
                    "value": value,
                },
            },
        }

        try:
            async with self.session.post(COMMAND_URL, headers=headers, json=body) as r:
                self.increase_api_calls()
                self.set_if_rate_limited(r.status)

                if r.status != 200:
                    return {}

                data = await r.json()

        except ClientError:
            self.logger.error(f"request error communicating with Govee sending command to device ({device_id})")
            return {}
        except Exception:
            self.logger.error(f"error communicating with Govee sending command to device ({device_id})")
            return {}

        new_capabilities = {}
        try:
            if "capability" in data and "state" in data["capability"] and data["capability"]["state"]["status"] == "success":
                capability = data["capability"]
                if isinstance(capability["value"], dict):
                    for key in capability["value"]:
                        new_capabilities[key] = capability["value"][key]
                else:
                    new_capabilities[capability["instance"]] = capability["value"]

                # only if we got any `capabilties` back from Govee will we update the `last_update`
                new_capabilities["lastUpdate"] = datetime.now(ZoneInfo(self.timezone))
        except Exception:
            self.logger.error(f"failed to process response sending command to device ({device_id})")
            return {}

        return new_capabilities
