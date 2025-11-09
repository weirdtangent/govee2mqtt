# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import aiohttp
from aiohttp import ClientError
from datetime import datetime
import json
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
        self.last_call_date = datetime.strptime(last_call_date, "%Y-%m-%d").date()

    def increase_api_calls(self: Govee2Mqtt) -> None:
        if not self.last_call_date or self.last_call_date != datetime.now(tz=ZoneInfo(self.timezone)).date():
            self.reset_api_call_count()
        self.api_calls += 1

    def reset_api_call_count(self: Govee2Mqtt) -> None:
        self.api_calls = 0
        self.last_call_date = datetime.now(tz=ZoneInfo(self.timezone)).date()
        self.logger.debug("Reset api call count for new day")

    def get_api_calls(self: Govee2Mqtt) -> int:
        return self.api_calls

    def is_rate_limited(self: Govee2Mqtt) -> bool:
        return self.rate_limited

    def get_headers(self: Govee2Mqtt) -> dict[str, str]:
        return {"Content-Type": "application/json", "Govee-API-Key": self.api_key}

    async def get_device_list(self: Govee2Mqtt) -> list[dict[str, Any]]:
        headers = self.get_headers()

        try:
            async with self.session.get(DEVICE_LIST_URL, headers=headers) as r:
                self.increase_api_calls()

                self.rate_limited = r.status == 429
                if r.status != 200:
                    if r.status == 429:
                        self.logger.warning("Rate-limited by Govee getting device list")
                    else:
                        self.logger.error(f"Error ({r.status}) getting device list")
                    return []

                data = await r.json()

        except ClientError:
            self.logger.error("Request error communicating with Govee for device list")
            return []
        except Exception:
            self.logger.error("Error communicating with Govee for device list")
            return []

        result = data.get("data", [])
        if not isinstance(result, list):
            self.logger.error(f"Unexpected response type from Govee: {type(result).__name__}")
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
                self.rate_limited = r.status == 429

                if r.status != 200:
                    if r.status == 429:
                        self.logger.error(f"Rate-limited by Govee getting device ({device_id})")
                    else:
                        self.logger.error(f"Error ({r.status}) getting device ({device_id})")
                    return {}

                data = await r.json()

        except aiohttp.ClientError as e:
            self.logger.error(f"Request error communicating with Govee for device ({device_id}): {e}")
            return {}
        except Exception as e:
            self.logger.error(f"Error communicating with Govee for device ({device_id}): {e}")
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

                self.rate_limited = r.status == 429
                if r.status != 200:
                    if r.status == 429:
                        self.logger.error(f"Rate-limited by Govee sending command to device ({device_id})")
                    else:
                        self.logger.error(f"Error ({r.status}) sending command to device ({device_id})")
                    return {}

                data = await r.json()
                self.logger.debug(f"Raw response from Govee: {data}")

        except ClientError:
            self.logger.error(f"Request error communicating with Govee sending command to device ({device_id})")
            return {}
        except Exception:
            self.logger.error(f"Error communicating with Govee sending command to device ({device_id})")
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
            self.logger.error(f"Failed to process response sending command to device ({device_id})")
            return {}

        return new_capabilities
