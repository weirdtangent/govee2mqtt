# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class TopicsMixin:

    # Device properties ---------------------------------------------------------------------------

    def get_device_name(self: Govee2Mqtt, device_id: str) -> str:
        return cast(str, self.devices[device_id]["component"]["name"])

    def get_raw_id(self: Govee2Mqtt, device_id: str) -> str:
        return cast(str, self.states[device_id]["internal"]["raw_id"])

    def get_device_sku(self: Govee2Mqtt, device_id: str) -> str:
        return cast(str, self.states[device_id]["internal"]["sku"])

    def get_component(self: Govee2Mqtt, device_id: str) -> dict[str, Any]:
        if device_id in self.devices:
            return cast(dict, self.devices[device_id]["component"])
        if "_" not in device_id:
            raise ValueError(f"Cannot get_component for {device_id}")
        parts = device_id.split("_")
        return cast(dict, self.devices[parts[0]]["modes"][parts[1]])

    def get_component_type(self: Govee2Mqtt, device_id: str) -> dict[str, Any]:
        return cast(dict, self.devices[device_id]["component"]["component_type"])

    def get_modes(self: Govee2Mqtt, device_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.devices[device_id].get("modes", {}))

    def get_mode(self: Govee2Mqtt, device_id: str, mode_name: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.devices[device_id]["modes"][mode_name])

    def get_device_state_topic(self: Govee2Mqtt, device_id: str, mode_name: str = "") -> str:
        component = self.get_mode(device_id, mode_name) if mode_name else self.get_component(device_id)

        match component["component_type"]:
            case "camera":
                return cast(str, component["topic"])
            case "image":
                return cast(str, component["image_topic"])
            case _:
                return cast(str, component.get("stat_t") or component.get("state_topic"))

    def get_device_image_topic(self: Govee2Mqtt, device_id: str) -> str:
        component = self.get_component(device_id)
        return cast(str, component["topic"])

    def get_device_availability_topic(self: Govee2Mqtt, device_id: str) -> str:
        component = self.get_component(device_id)
        return cast(str, component.get("avty_t") or component.get("availability_topic"))
