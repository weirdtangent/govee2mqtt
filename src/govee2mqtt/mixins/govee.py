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
            # case "fan":
            #     return await self.build_fan(device)
            # case "air_purifier":
            #     return await self.build_air_purifier(device)
            case "humidifier":
                return await self.build_humidifier(device)
            # case "dehumidifier":
            #     return await self.build_dehumidifier(device)
            # case "aroma_diffuser":
            case _:
                if device_class:
                    self.logger.debug(
                        f'recognized Govee device class "{device_class}" but not handled yet, for device "{device["deviceName"]}" [{device["sku"]}] ({device["device"]})'
                    )
                return ""

    def classify_device(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        sku = device["sku"]

        # fans are H710x
        if re.compile(r"^H710\d{1,}$").match(sku):
            return "fan"
        # air purifiers are H712x
        if re.compile(r"^H712\d{1,}$").match(sku):
            return "air_purifier"
        # humidifiers are H714x
        if re.compile(r"^H714\d{1,}$").match(sku):
            return "humidifier"
        # dehumidifiers are H715x
        if re.compile(r"^H715\d{1,}$").match(sku):
            return "dehumidifier"
        # aroma diffusers are H716x
        if re.compile(r"^H716\d{1,}$").match(sku):
            return "aroma_diffuser"
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
            "cmps": self.build_light_components(device_id, light),
        }

        self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": light.get("sku")})
        await self.prepare_device(device, raw_id, device_id, "light")
        return device_id

    async def build_humidifier(self: Govee2Mqtt, humidifier: dict[str, Any]) -> str:
        raw_id = str(humidifier["device"])
        device_id = raw_id.replace(":", "").upper()

        min_humidity = 0
        max_humidity = 100
        nightlight_options = ["Off"]
        nightlight_scene_labels: dict[int, str] = {0: "Off"}
        work_mode_options: list[str] = []
        manual_level_values: list[int] = []
        work_mode_value_labels: dict[int, str] = {}
        manual_level_labels: dict[int, str] = {}
        device_has: dict[str, bool] = {}

        for cap in humidifier.get("capabilities", []):
            device_has[cap["instance"]] = True
            match cap["instance"]:
                case "humidity":
                    min_humidity = cap.get("parameters", {}).get("range", {}).get("min", 0)
                    max_humidity = cap.get("parameters", {}).get("range", {}).get("max", 100)
                case "nightlightScene":
                    for option in cap.get("parameters", {}).get("options", []):
                        name = option.get("name")
                        value = option.get("value")
                        if not name:
                            continue
                        if isinstance(value, int):
                            nightlight_scene_labels[value] = name
                        if name not in nightlight_options:
                            nightlight_options.append(name)
                case "workMode":
                    fields = cap.get("parameters", {}).get("fields", [])
                    mode_field = next((f for f in fields if f.get("fieldName") == "workMode"), None)
                    mode_value_field = next((f for f in fields if f.get("fieldName") == "modeValue"), None)

                    if mode_value_field:
                        for option in mode_value_field.get("options", []):
                            if option.get("name", "").lower() != "manual":
                                continue
                            for value in option.get("options", []):
                                level = value.get("value")
                                if isinstance(level, int):
                                    manual_level_values.append(level)
                                    manual_level_labels[level] = manual_level_labels.get(level, f"Mist Level {level}")

                    if mode_field:
                        for option in mode_field.get("options", []):
                            name = option.get("name")
                            value = option.get("value")
                            if not name:
                                continue
                            if isinstance(value, int):
                                work_mode_value_labels[value] = name
                            if name.lower() == "manual" and manual_level_values:
                                for level in sorted(set(manual_level_values)):
                                    label = manual_level_labels.get(level, f"Mist Level {level}")
                                    if label not in work_mode_options:
                                        work_mode_options.append(label)
                            elif name not in work_mode_options:
                                work_mode_options.append(name)

        cmps: dict[str, dict[str, Any]] = {}

        cmps["power"] = {
            "p": "switch",
            "name": "Power",
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "humidifier"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "power"),
            "cmd_t": self.mqtt_helper.cmd_t(device_id, "power"),
            "device_class": "switch",
            "icon": "mdi:power",
        }
        self.upsert_state(device_id, switch={"power": "OFF"})

        if device_has.get("brightness", False) or device_has.get("colorRgb", False):
            cmps.update(self.build_light_components(device_id, humidifier))
            self.upsert_state(device_id, light={"state": "OFF"})

        if device_has.get("humidity", False):
            cmps["humidity"] = {
                "p": "number",
                "name": "Humidity",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "humidity"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "number", "humidity"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "number", "humidity"),
                "min": min_humidity,
                "max": max_humidity,
                "step": 1,
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "device_class": "humidity",
                "entity_category": "config",
                "icon": "mdi:water-percent",
            }
            self.upsert_state(device_id, number={"humidity": 50})

        if device_has.get("warmMistToggle", False):
            cmps["warm_mist"] = {
                "p": "switch",
                "name": "Warm Mist",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "switch"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "warm_mist"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "warm_mist"),
                "device_class": "switch",
                "icon": "mdi:heat-wave",
            }
            self.upsert_state(device_id, switch={"warm_mist": "OFF"})

        if device_has.get("workMode", False) and work_mode_options:
            cmps["work_mode"] = {
                "p": "select",
                "name": "Work Mode",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "work_mode"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "select", "work_mode"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "select", "work_mode"),
                "options": work_mode_options,
                "icon": "mdi:water-pump",
            }
            default_work_mode = "Auto" if "Auto" in work_mode_options else work_mode_options[0]
            self.upsert_state(device_id, select={"work_mode": default_work_mode})

        if device_has.get("nightlightToggle", False) and nightlight_options:
            cmps["night_light"] = {
                "p": "select",
                "name": "Nightlight Scene",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "nightlight_scene"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "select", "nightlight_scene"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "light", "nightlight_scene"),
                "options": nightlight_options,
                "icon": "mdi:weather-night",
            }
            self.upsert_state(device_id, select={"nightlight_scene": nightlight_options[0]})

        device = {
            "stat_t": self.mqtt_helper.stat_t(device_id, "humidifier"),
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "device": {
                "name": humidifier["deviceName"],
                "identifiers": [
                    self.mqtt_helper.device_slug(device_id),
                ],
                "manufacturer": "Govee",
                "model": humidifier["sku"],
                "connections": [
                    ["mac", humidifier["device"]],
                ],
                "via_device": self.service,
            },
            "origin": {"name": self.service_name, "sw": self.config["version"], "support_url": "https://github.com/weirdTangent/govee2mqtt"},
            "qos": self.qos,
            "cmps": cmps,
        }

        internal: dict[str, Any] = {"raw_id": raw_id, "sku": humidifier.get("sku")}
        if work_mode_value_labels:
            internal["work_mode_value_labels"] = work_mode_value_labels
        if manual_level_labels:
            internal["manual_level_labels"] = manual_level_labels
        if nightlight_scene_labels:
            internal["nightlight_scene_labels"] = nightlight_scene_labels
        self.upsert_state(device_id, internal=internal)

        await self.prepare_device(device, raw_id, device_id, "humidifier")
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
                            "temperature": {
                                "p": "sensor",
                                "name": "Temperature",
                                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "temperature"),
                                "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                                "device_class": "temperature",
                                "state_class": "measurement",
                                "unit_of_measurement": "°F",
                                "icon": "mdi:thermometer",
                            }
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
                            "humidity": {
                                "p": "sensor",
                                "name": "Humidity",
                                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "humidity"),
                                "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                                "device_class": "humidity",
                                "state_class": "measurement",
                                "unit_of_measurement": "%",
                                "icon": "mdi:water-percent",
                            }
                        },
                    }
                case _:
                    continue

            if device_id:
                self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": sensor.get("sku")})
                await self.prepare_device(device, raw_id, device_id, sensor["deviceName"])
                return device_id

        return ""

    def build_light_components(self: Govee2Mqtt, device_id: str, light: dict[str, Any]) -> dict[str, dict[str, Any]]:
        light_is_nightlight = False

        components: dict[str, dict[str, Any]] = {
            "light": {
                "p": "light",
                "name": "Light",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "light"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "light", "state"),
                "avty_t": self.mqtt_helper.avty_t(device_id),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "light"),
                "supported_color_modes": ["onoff"],
            },
        }

        # adjust our light component based on what this Govee light can support
        for cap in light["capabilities"]:
            match cap["instance"]:
                case "brightness":
                    components["light"]["supported_color_modes"].append("brightness")
                    components["light"]["brightness_scale"] = cap["parameters"]["range"]["max"]
                    components["light"]["brightness_state_topic"] = self.mqtt_helper.stat_t(device_id, "light", "brightness")
                    components["light"]["brightness_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light", "brightness")
                case "powerSwitch":
                    components["light"]["supported_color_modes"].append("onoff")
                case "colorRgb":
                    components["light"]["supported_color_modes"].append("rgb")
                    components["light"]["rgb_state_topic"] = self.mqtt_helper.stat_t(device_id, "light", "rgb_color")
                    components["light"]["rgb_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light", "rgb_color")
                    self.upsert_state(device_id, light={"rgb_max": cap["parameters"]["range"]["max"] or 16777215})
                case "colorTemperatureK":
                    components["light"]["supported_color_modes"].append("color_temp")
                    components["light"]["color_temp_kelvin"] = True
                    components["light"]["color_temp_state_topic"] = self.mqtt_helper.stat_t(device_id, "light", "color_temp")
                    components["light"]["color_temp_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light", "color_temp")
                    components["light"]["min_kelvin"] = cap["parameters"]["range"]["min"] or 2000
                    components["light"]["max_kelvin"] = cap["parameters"]["range"]["max"] or 9000
                case "gradientToggle":
                    components["gradient"] = {
                        "p": "switch",
                        "name": "Gradient",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "gradient"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "gradient"),
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "gradient"),
                        "icon": ("mdi:gradient-horizontal" if light["sku"] == "H6042" else "mdi:gradient-vertical"),
                    }
                case "nightlightToggle":
                    light_is_nightlight = True
                case "dreamViewToggle":
                    components["dreamview"] = {
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

        # If a light supports a color mode (rgb or color_temp), drop simpler light components
        cmpset = set(components["light"]["supported_color_modes"])
        if "rgb" in cmpset or "color_temp" in cmpset:
            cmpset.discard("onoff")
            cmpset.discard("brightness")
            components["light"].pop("brightness_scale", None)
            components["light"].pop("brightness_state_topic", None)
            components["light"].pop("brightness_command_topic", None)
        components["light"]["supported_color_modes"] = list(cmpset)

        # if light really is a nightlight, rename it and move it to the nightlight component
        if light_is_nightlight:
            components["light"]["name"] = "Nightlight"
            components["light"]["uniq_id"] = self.mqtt_helper.dev_unique_id(device_id, "nightlight")
            components["nightlight"] = components.pop("light")

        return components

    async def prepare_device(self: Govee2Mqtt, device: dict[str, Any], raw_id: str, device_id: str, type: str) -> None:
        self.upsert_device(device_id, component=device)
        if "internal" not in self.states.get(device_id, {}):
            self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": device["device"]["model"]})
        await self.build_device_states(device_id)

        if not self.is_discovered(device_id):
            self.logger.info(f'added new {type}: "{device["device"]["name"]}" [Govee {device["device"]["model"]}] ({device_id})')
            await self.publish_device_discovery(device_id)

        await self.publish_device_availability(device_id, online=True)
        await self.publish_device_state(device_id)
