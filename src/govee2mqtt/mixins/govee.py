# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import re

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class GoveeMixin:
    async def refresh_device_list(self: Govee2Mqtt) -> None:
        self.logger.info(f"refreshing device list from Govee (every {self.device_list_interval} sec)")

        govee_devices = await self.get_device_list()
        if not govee_devices:
            return

        seen_devices: set[str] = set()

        # Build all components concurrently
        tasks = [self.build_component(device) for device in govee_devices]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful device IDs
        for result in results:
            if isinstance(result, Exception):
                self.logger.error("error during build_component", exc_info=result)
            elif result and isinstance(result, str):
                seen_devices.add(result)

        # Mark missing devices offline
        missing_devices = set(self.devices.keys()) - seen_devices
        for device_id in missing_devices:
            await self.publish_device_availability(device_id, online=False)
            self.logger.warning(f"device {device_id} not seen in Govee API list — marked offline")

        # Handle first discovery completion
        if not self.discovery_complete:
            await asyncio.sleep(5)
            await self.rediscover_all()
            self.logger.info("first-time device setup and discovery is done")
            self.discovery_complete = True

    # convert Govee device capabilities into MQTT components
    async def build_component(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        device_class = self.classify_device(device)
        match device_class:
            case "light":
                return await self.build_light(device)
            case "sensor":
                return await self.build_sensor(device)
        return ""

    def classify_device(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        sku = device["sku"]

        # lights are H6xxx, H7xxx, H8xxx
        if re.compile(r"^H[678]\d{3,}$").match(sku):
            return "light"
        # sensors are H5xxx
        if re.compile(r"^H5\d{3,}$").match(sku):
            return "sensor"

        # If we reach here, it's unsupported — log details (the first time)for future handling
        if not self.discovery_complete:
            device_name = device.get("deviceName", "Unknown Device")
            device_id = device.get("device", "Unknown ID")
            self.logger.debug(f'unrecognized Govee device type: "{device_name}" [{sku}] ({device_id})')
        return ""

    async def build_light(self: Govee2Mqtt, light: dict[str, Any]) -> str:
        raw_id = str(light["device"])
        device_id = raw_id.replace(":", "").upper()

        device = {
            "stat_t": self.mqtt_helper.stat_t(device_id, "light"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device": {
                "name": light["deviceName"],
                "identifiers": [
                    self.mqtt_helper.device_slug(device_id),
                ],
                "manufacturer": "Govee",
                "model": light["sku"],
                "connections": [
                    ["mac", light["device"]],
                ],
                "via_device": self.service,
            },
            "origin": {"name": self.service_name, "sw": self.config["version"], "support_url": "https://github.com/weirdTangent/govee2mqtt"},
            "qos": self.qos,
            "cmps": {
                "light": {
                    "p": "light",
                    "name": light["deviceName"],
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "light"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "light", "state"),
                    "avty_t": self.mqtt_helper.avty_t(device_id),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "light"),
                    "supported_color_modes": ["onoff"],
                },
            },
        }
        self.upsert_state(device_id, light={"state": "OFF"})

        # adjust our light component based on what this Govee light can support
        for cap in light["capabilities"]:
            match cap["instance"]:
                case "brightness":
                    device["cmps"]["light"]["supported_color_modes"].append("brightness")
                    device["cmps"]["light"]["brightness_scale"] = cap["parameters"]["range"]["max"]
                    device["cmps"]["light"]["brightness_state_topic"] = self.mqtt_helper.stat_t(device_id, "light", "brightness")
                    device["cmps"]["light"]["brightness_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light", "brightness")
                case "powerSwitch":
                    device["cmps"]["light"]["supported_color_modes"].append("onoff")
                case "colorRgb":
                    device["cmps"]["light"]["supported_color_modes"].append("rgb")
                    device["cmps"]["light"]["rgb_state_topic"] = self.mqtt_helper.stat_t(device_id, "light", "rgb_color")
                    device["cmps"]["light"]["rgb_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light", "rgb_color")
                    self.upsert_state(device_id, light={"rgb_max": cap["parameters"]["range"]["max"] or 16777215})
                case "colorTemperatureK":
                    device["cmps"]["light"]["supported_color_modes"].append("color_temp")
                    device["cmps"]["light"]["color_temp_kelvin"] = True
                    device["cmps"]["light"]["color_temp_state_topic"] = self.mqtt_helper.stat_t(device_id, "light", "color_temp")
                    device["cmps"]["light"]["color_temp_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light", "color_temp")
                    device["cmps"]["light"]["min_kelvin"] = cap["parameters"]["range"]["min"] or 2000
                    device["cmps"]["light"]["max_kelvin"] = cap["parameters"]["range"]["max"] or 9000
                case "gradientToggle":
                    device["cmps"]["gradient"] = {
                        "p": "switch",
                        "name": "Gradient",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "gradient"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "gradient"),
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "gradient"),
                        "icon": ("mdi:gradient-horizontal" if light["sku"] == "H6042" else "mdi:gradient-vertical"),
                    }
                case "nightlightToggle":
                    device["cmps"]["nightlight"] = {
                        "p": "switch",
                        "name": "Nightlight",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "nightlight"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "nightlight"),
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "nightlight"),
                        "icon": "mdi:weather-night",
                    }
                case "dreamViewToggle":
                    device["cmps"]["dreamview"] = {
                        "p": "switch",
                        "name": "Dreamview",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "dreamview"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "dreamview"),
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "dreamview"),
                        "icon": "mdi:creation",
                    }

                # case 'musicMode':
                #     # setup to store state
                #     device_states['music'] = { 'mode': 'Off', 'sensitivity': 100 }

                #     music_options = [ 'Off' ]
                #     device_states['music']['options'] = { 'Off': 0 }

                #     for field in cap['parameters']['fields']:
                #         match field['fieldName']:
                #             case "musicMode":
                #                 for option in field["options"]:
                #                     music_options.append(option["name"])
                #                     device_states["music"]["options"][
                #                         option["name"]
                #                     ] = option["value"]
                #             case 'sensitivity':
                #                 music_min = field['range']['min']
                #                 music_max = field['range']['max']
                #                 music_step = field['range']['precision']
                #                 device_states['music']['sensitivity'] = 100

                #     components[self.mqtt_helper.device_slug(device_id, 'music_mode')] = {
                #         'name': 'Music Mode',
                #         'platform': 'sensor',
                #         'device_class': 'enum',
                #         'options': music_options,
                #         'state_topic': music_topic,
                #         'availability_topic': availability_topic,
                #         'command_topic': self.mqtt_helper.cmd_t(device_id, 'music_mode'),
                #         'value_template': '{{ value_json.mode }}',
                #         'unique_id': self.mqtt_helper.device_slug(device_id, 'music_mode'),
                #     }
                #     components[self.mqtt_helper.device_slug(device_id, 'music_sensitivity')] = {
                #         'name': 'Music Sensitivity',
                #         'platform': 'number',
                #         'icon': 'mdi:numeric',
                #         'min': music_min,
                #         'max': music_max,
                #         'step': music_step,
                #         'state_topic': music_topic,
                #         'availability_topic': availability_topic,
                #         'command_topic': self.mqtt_helper.cmd_t(device_id, 'music_sensitivity'),
                #         'value_template': '{{ value_json.sensitivity }}',
                #         'unique_id': self.mqtt_helper.device_slug(device_id, 'music_sensitivity'),
                #     }

        # If a color mode (rgb or color_temp) is supported, drop simpler cmps
        cmpset = set(device["cmps"]["light"]["supported_color_modes"])
        if "rgb" in cmpset or "color_temp" in cmpset:
            cmpset.discard("onoff")
            cmpset.discard("brightness")
            device["cmps"]["light"].pop("brightness_scale", None)
            device["cmps"]["light"].pop("brightness_state_topic", None)
            device["cmps"]["light"].pop("brightness_command_topic", None)
        device["cmps"]["light"]["supported_color_modes"] = list(cmpset)

        # watch for capabilities we don't handle
        unsupported = [
            cap["instance"]
            for cap in light["capabilities"]
            if cap["instance"]
            not in [
                "brightness",
                "powerSwitch",
                "colorRgb",
                "colorTemperatureK",
                "gradientToggle",
                "nightlightToggle",
                "dreamViewToggle",
            ]
        ]
        if unsupported and not self.discovery_complete:
            self.logger.debug(f'unhandled light capabilities for {light["deviceName"]}: {unsupported}')

        self.upsert_device(device_id, component=device)
        self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": light.get("sku", None)})
        await self.build_device_states(device_id)

        if not self.is_discovered(device_id):
            self.logger.info(f'added new light: "{light["deviceName"]}" [Govee {light["sku"]}] ({device_id})')
            await self.publish_device_discovery(device_id)

        await self.publish_device_availability(device_id, online=True)
        await self.publish_device_state(device_id)

        return device_id

    async def build_sensor(self: Govee2Mqtt, sensor: dict[str, Any]) -> str:
        raw_id = sensor["device"]
        parent = raw_id.replace(":", "").upper()

        for cap in sensor["capabilities"]:
            device_id = None
            device = None
            match cap["instance"]:
                case "sensorTemperature":
                    device_id = f"{parent}_temp"
                    device = {
                        "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                        "avty_t": self.mqtt_helper.avty_t(parent, "sensor"),
                        "device": {
                            "name": sensor["deviceName"],
                            "identifiers": [
                                self.mqtt_helper.device_slug(device_id),
                            ],
                            "manufacturer": "Govee",
                            "model": sensor["sku"],
                            "connections": [
                                ["mac", sensor["device"]],
                            ],
                            "via_device": self.service,
                        },
                        "origin": {"name": self.service_name, "sw": self.config["version"], "support_url": "https://github.com/weirdTangent/govee2mqtt"},
                        "qos": self.qos,
                        "cmps": {
                            "p": "sensor",
                            "name": "Temperature",
                            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "temperature"),
                            "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                            "device_class": "temperature",
                            "state_class": "measurement",
                            "unit_of_measurement": "°F",
                            "icon": "mdi:thermometer",
                        },
                    }

                case "sensorHumidity":
                    device_id = f"{parent}_hmdy"
                    device = {
                        "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                        "avty_t": self.mqtt_helper.avty_t(parent, "sensor"),
                        "device": {
                            "name": sensor["deviceName"],
                            "identifiers": [
                                self.mqtt_helper.device_slug(device_id),
                            ],
                            "manufacturer": "Govee",
                            "model": sensor["sku"],
                            "connections": [
                                ["mac", sensor["device"]],
                            ],
                            "via_device": self.service,
                        },
                        "origin": {"name": self.service_name, "sw": self.config["version"], "support_url": "https://github.com/weirdTangent/govee2mqtt"},
                        "qos": self.qos,
                        "cmps": {
                            "p": "sensor",
                            "name": "Humidity",
                            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "humidity"),
                            "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                            "device_class": "humidity",
                            "state_class": "measurement",
                            "unit_of_measurement": "%",
                            "icon": "mdi:water-percent",
                        },
                    }
                case _:
                    continue

            if device_id:
                self.upsert_device(device_id, component=device, cmps=device["cmps"])
                self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": sensor.get("sku", None)})
                await self.build_device_states(device_id)

                if not self.is_discovered(device_id):
                    self.logger.info(f'added new sensor: "{sensor["deviceName"]}" [Govee {sensor["sku"]}] ({device_id})')

                await self.publish_device_discovery(device_id)
                await self.publish_device_availability(device_id, online=True)
                await self.publish_device_state(device_id)

                return device_id

        return ""
