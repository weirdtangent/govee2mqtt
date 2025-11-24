# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import re

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


SKU_CLASS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^H710\d+$"), "fan"),
    (re.compile(r"^H712\d+$"), "air_purifier"),
    (re.compile(r"^H714\d+$"), "humidifier"),
    (re.compile(r"^H715\d+$"), "dehumidifier"),
    (re.compile(r"^H716\d+$"), "aroma_diffuser"),
    (re.compile(r"^H[678]\d{3,}$"), "light"),
    (re.compile(r"^H5\d{3,}$"), "sensor"),
]


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
            self.logger.warning(f"device {self.get_device_name(device_id)} not seen in Govee API list — marked offline")

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
            case "air_purifier":
                return await self.build_air_purifier(device)
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

        for pattern, device_class in SKU_CLASS_PATTERNS:
            if pattern.match(sku):
                return device_class

        # If we reach here, it's unsupported — log details (the first time)for future handling
        if not self.discovery_complete:
            device_name = device.get("deviceName", "Unknown Device")
            device_id = device.get("device", "Unknown ID")
            self.logger.debug(f'unrecognized Govee device type: "{device_name}" [{sku}] ({device_id})')
        return ""

    async def build_light(self: Govee2Mqtt, light: dict[str, Any]) -> str:
        raw_id = str(light["device"])
        device_id = raw_id.replace(":", "").upper()

        components = self.build_light_components(device_id, light)
        device = _build_device_payload(self, device_id, light, "light", components)

        self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": light.get("sku")})
        await self.prepare_device(device, raw_id, device_id, "light")
        return device_id

    async def build_air_purifier(self: Govee2Mqtt, air_purifier: dict[str, Any]) -> str:
        raw_id = str(air_purifier["device"])
        device_id = raw_id.replace(":", "").upper()

        work_mode_options: list[str] = []
        gear_mode_values: list[int] = []
        work_mode_value_labels: dict[int, str] = {}
        gear_mode_labels: dict[int, str] = {}
        device_has: dict[str, bool] = {}

        for cap in air_purifier.get("capabilities", []):
            device_has[cap["instance"]] = True
            match cap["instance"]:
                case "workMode":
                    fields = cap.get("parameters", {}).get("fields", [])
                    mode_field = next((f for f in fields if f.get("fieldName") == "workMode"), None)
                    mode_value_field = next((f for f in fields if f.get("fieldName") == "modeValue"), None)

                    if mode_value_field:
                        for option in mode_value_field.get("options", []):
                            name = option.get("name")
                            if not isinstance(name, str) or name.lower() != "gearmode":
                                continue
                            for value in option.get("options", []):
                                level = value.get("value")
                                if isinstance(level, int):
                                    gear_mode_values.append(level)
                                    gear_mode_labels[level] = value.get("name") or f"Gear Level {level}"

                    if mode_field:
                        base_mode_names: list[str] = []
                        gear_mode_present = False
                        for option in mode_field.get("options", []):
                            name = option.get("name")
                            value = option.get("value")
                            if not name:
                                continue
                            if isinstance(value, int):
                                work_mode_value_labels[value] = name
                            if isinstance(name, str) and name.lower() == "gearmode":
                                gear_mode_present = True
                                continue
                            if name not in work_mode_options and name not in base_mode_names:
                                base_mode_names.append(name)
                        for base in base_mode_names:
                            work_mode_options.append(base)
                        if gear_mode_present and gear_mode_values:
                            for level in sorted(set(gear_mode_values)):
                                label = gear_mode_labels.get(level, f"Gear Level {level}")
                                if label not in work_mode_options:
                                    work_mode_options.append(label)

        cmps: dict[str, dict[str, Any]] = {
            "power": {
                "p": "switch",
                "name": "Power",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "air_purifier"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "power"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "power"),
                "device_class": "switch",
                "icon": "mdi:power",
            }
        }
        self.upsert_state(device_id, switch={"power": "OFF"})

        if device_has.get("workMode", False) and work_mode_options:
            cmps["work_mode"] = {
                "p": "select",
                "name": "Work Mode",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "work_mode"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "select", "work_mode"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "select", "work_mode"),
                "options": work_mode_options,
                "icon": "mdi:air-purifier",
            }
            default_work_mode = "Auto" if "Auto" in work_mode_options else work_mode_options[0]
            self.upsert_state(device_id, select={"work_mode": default_work_mode})

        if device_has.get("filterLifeTime", False):
            cmps["filter_life"] = {
                "p": "sensor",
                "name": "Filter Life",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "filter_life"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "filter_life"),
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "entity_category": "diagnostic",
                "icon": "mdi:air-filter",
            }

        if device_has.get("airQuality", False):
            cmps["air_quality"] = {
                "p": "sensor",
                "name": "Air Quality",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "air_quality"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "sensor", "air_quality"),
                "device_class": "aqi",
                "icon": "mdi:air-purifier",
            }

        device = _build_device_payload(self, device_id, air_purifier, "air_purifier", cmps)

        internal: dict[str, Any] = {"raw_id": raw_id, "sku": air_purifier.get("sku")}
        if work_mode_value_labels:
            internal["work_mode_value_labels"] = work_mode_value_labels
        if gear_mode_labels:
            internal["gear_mode_labels"] = gear_mode_labels
        self.upsert_state(device_id, internal=internal)

        await self.prepare_device(device, raw_id, device_id, "air_purifier")
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

        device = _build_device_payload(self, device_id, humidifier, "humidifier", cmps)

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

        dynamic_scene_caps: dict[str, dict[str, Any]] = {}
        segment_range: dict[str, int] | None = None
        segment_brightness_range: dict[str, int] | None = None
        segment_color_range: dict[str, int] | None = None
        has_segment_brightness = False
        has_segment_color = False

        music_mode_options: list[str] = []
        music_mode_values: dict[str, int] = {}
        music_sensitivity_range = {"min": 0, "max": 100, "step": 1}
        music_auto_color_values: dict[str, int] = {}
        music_rgb_range = {"min": 0, "max": 16777215}
        music_rgb_supported = False
        has_music_capability = False

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
                    self.upsert_state(device_id, switch={"gradient": "OFF"})
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
                    self.upsert_state(device_id, switch={"dreamview": "OFF"})
                case "dynamic_scene":
                    instance = cap.get("instance")
                    if not instance:
                        continue
                    scene_options: list[str] = []
                    scene_labels: dict[Any, str] = {}
                    for option in cap.get("parameters", {}).get("options", []):
                        name = option.get("name")
                        value = option.get("value")
                        if not name:
                            continue
                        scene_options.append(name)
                        if value is not None:
                            scene_labels[value] = name
                    dynamic_scene_caps[instance] = {"options": scene_options, "labels": scene_labels}
                case "segmentedBrightness":
                    has_segment_brightness = True
                    for field in cap.get("parameters", {}).get("fields", []):
                        match field.get("fieldName"):
                            case "segment":
                                elem_range = field.get("elementRange", {})
                                segment_range = {
                                    "min": elem_range.get("min", 0) or 0,
                                    "max": elem_range.get("max", 0) or 0,
                                }
                            case "brightness":
                                rng = field.get("range", {})
                                segment_brightness_range = {
                                    "min": rng.get("min", 0) or 0,
                                    "max": rng.get("max", 100) or 100,
                                    "step": rng.get("precision", 1) or 1,
                                }
                case "segmentedColorRgb":
                    has_segment_color = True
                    for field in cap.get("parameters", {}).get("fields", []):
                        match field.get("fieldName"):
                            case "segment":
                                elem_range = field.get("elementRange", {})
                                segment_range = {
                                    "min": elem_range.get("min", 0) or 0,
                                    "max": elem_range.get("max", 0) or 0,
                                }
                            case "rgb":
                                rng = field.get("range", {})
                                segment_color_range = {
                                    "min": rng.get("min", 0) or 0,
                                    "max": rng.get("max", 16777215) or 16777215,
                                }
                case "musicMode":
                    has_music_capability = True
                    fields = cap.get("parameters", {}).get("fields", [])
                    for field in fields:
                        field_name = field.get("fieldName")
                        match field_name:
                            case "musicMode":
                                for option in field.get("options", []):
                                    name = option.get("name")
                                    value = option.get("value")
                                    if isinstance(name, str) and isinstance(value, int):
                                        if name not in music_mode_options:
                                            music_mode_options.append(name)
                                        music_mode_values[name] = value
                            case "sensitivity":
                                rng = field.get("range", {})
                                music_sensitivity_range = {
                                    "min": rng.get("min", 0) or 0,
                                    "max": rng.get("max", 100) or 100,
                                    "step": rng.get("precision", 1) or 1,
                                }
                            case "autoColor":
                                for option in field.get("options", []):
                                    name = option.get("name")
                                    value = option.get("value")
                                    if isinstance(name, str) and isinstance(value, int):
                                        music_auto_color_values[name.lower()] = value
                            case "rgb":
                                rng = field.get("range", {})
                                music_rgb_supported = True
                                music_rgb_range = {
                                    "min": rng.get("min", 0) or 0,
                                    "max": rng.get("max", 16777215) or 16777215,
                                }

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

        dynamic_scene_labels_internal: dict[str, dict[Any, str]] = {}
        dynamic_scene_instances_map: dict[str, str] = {}
        dynamic_scene_components_map: dict[str, str] = {}
        existing_select_state = self.states.get(device_id, {}).get("select", {})

        for instance, scene_data in dynamic_scene_caps.items():
            if not instance:
                continue
            options_list = scene_data.get("options", [])
            if not options_list:
                continue
            scene_key = self._scene_component_key(instance)
            scene_name = re.sub(r"(?<!^)(?=[A-Z])", " ", instance).title()
            default_scene = existing_select_state.get(scene_key)
            if default_scene not in options_list:
                default_scene = options_list[0]
            components[scene_key] = {
                "p": "select",
                "name": scene_name,
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, scene_key),
                "stat_t": self.mqtt_helper.stat_t(device_id, "select", scene_key),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "select", scene_key),
                "options": options_list,
                "icon": "mdi:movie-open-outline",
            }
            self.upsert_state(device_id, select={scene_key: default_scene})
            dynamic_scene_labels_internal[instance] = scene_data.get("labels", {})
            dynamic_scene_instances_map[instance] = scene_key
            dynamic_scene_components_map[scene_key] = instance

        existing_segment_state = self.states.get(device_id, {}).get("segments", {})
        if segment_range and (has_segment_brightness or has_segment_color):
            min_segment = int(segment_range.get("min", 0))
            max_segment = int(segment_range.get("max", min_segment))
            segment_options = [self._segment_option_label(i) for i in range(min_segment, max_segment + 1)]
            default_segment = existing_segment_state.get("selected_segment", min_segment)
            if default_segment < min_segment or default_segment > max_segment:
                default_segment = min_segment

            components["segment_index"] = {
                "p": "select",
                "name": "Segment",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "segment_index"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "select", "segment_index"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "select", "segment_index"),
                "options": segment_options,
                "icon": "mdi:animation-outline",
            }
            self.upsert_state(device_id, select={"segment_index": self._segment_option_label(default_segment)})

            segments_state: dict[str, Any] = {
                "range": segment_range,
                "selected_segment": default_segment,
            }

            if has_segment_brightness and segment_brightness_range:
                brightness_min = int(segment_brightness_range.get("min", 0))
                brightness_max = int(segment_brightness_range.get("max", 100))
                brightness_step = segment_brightness_range.get("step", 1) or 1
                default_brightness = existing_segment_state.get("brightness", brightness_max)
                if default_brightness < brightness_min or default_brightness > brightness_max:
                    default_brightness = brightness_max
                components["segment_brightness"] = {
                    "p": "number",
                    "name": "Segment Brightness",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "segment_brightness"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "number", "segment_brightness"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "number", "segment_brightness"),
                    "min": brightness_min,
                    "max": brightness_max,
                    "step": brightness_step,
                    "mode": "slider",
                    "entity_category": "config",
                    "icon": "mdi:brightness-6",
                }
                self.upsert_state(device_id, number={"segment_brightness": default_brightness})
                segments_state["brightness"] = default_brightness
                segments_state["brightness_range"] = segment_brightness_range

            if has_segment_color and segment_color_range:
                color_min = int(segment_color_range.get("min", 0))
                color_max = int(segment_color_range.get("max", 16777215))
                default_rgb = existing_segment_state.get("rgb_value", color_min)
                if default_rgb < color_min or default_rgb > color_max:
                    default_rgb = color_min
                components["segment_rgb"] = {
                    "p": "number",
                    "name": "Segment RGB",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "segment_rgb"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "number", "segment_rgb"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "number", "segment_rgb"),
                    "min": color_min,
                    "max": color_max,
                    "step": 1,
                    "entity_category": "config",
                    "icon": "mdi:palette-outline",
                }
                self.upsert_state(device_id, number={"segment_rgb": default_rgb})
                segments_state["rgb_value"] = default_rgb
                segments_state["color_range"] = segment_color_range
                segments_state["rgb_max"] = color_max

            self.upsert_state(device_id, segments=segments_state)

        if has_music_capability and music_mode_options:
            default_music_mode = music_mode_options[0]
            components["music_mode"] = {
                "p": "select",
                "name": "Music Mode",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "music_mode"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "select", "music_mode"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "music_mode"),
                "options": music_mode_options,
                "icon": "mdi:music-note",
            }

            sensitivity_min = music_sensitivity_range["min"]
            sensitivity_max = music_sensitivity_range["max"]
            sensitivity_step = music_sensitivity_range["step"]
            default_sensitivity = min(max(80, sensitivity_min), sensitivity_max)

            components["music_sensitivity"] = {
                "p": "number",
                "name": "Music Sensitivity",
                "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "music_sensitivity"),
                "stat_t": self.mqtt_helper.stat_t(device_id, "number", "music_sensitivity"),
                "cmd_t": self.mqtt_helper.cmd_t(device_id, "music_sensitivity"),
                "min": sensitivity_min,
                "max": sensitivity_max,
                "step": sensitivity_step,
                "mode": "slider",
                "entity_category": "config",
                "icon": "mdi:music-note-plus",
            }

            if music_auto_color_values:
                components["music_auto_color"] = {
                    "p": "switch",
                    "name": "Music Auto Color",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "music_auto_color"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "music_auto_color"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "music_auto_color"),
                    "icon": "mdi:palette",
                }

            if music_rgb_supported:
                components["music_rgb"] = {
                    "p": "number",
                    "name": "Music RGB Value",
                    "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "music_rgb"),
                    "stat_t": self.mqtt_helper.stat_t(device_id, "number", "music_rgb"),
                    "cmd_t": self.mqtt_helper.cmd_t(device_id, "music_rgb"),
                    "min": music_rgb_range["min"],
                    "max": music_rgb_range["max"],
                    "step": 1,
                    "entity_category": "config",
                    "icon": "mdi:led-strip-variant",
                }

            existing_music_state = self.states.get(device_id, {}).get("music", {})
            auto_color_default_state = existing_music_state.get("auto_color_state")
            if auto_color_default_state is None:
                auto_color_default_state = False

            mode_initial = existing_music_state.get("mode", default_music_mode)
            sensitivity_initial = existing_music_state.get("sensitivity", default_sensitivity)
            rgb_initial = existing_music_state.get("rgb_value", music_rgb_range["min"] if music_rgb_supported else None)

            music_state: dict[str, Any] = {
                "options": music_mode_values,
                "mode": mode_initial,
                "sensitivity": sensitivity_initial,
                "sensitivity_range": music_sensitivity_range,
                "auto_color_values": music_auto_color_values,
                "auto_color_state": auto_color_default_state,
                "rgb_value": rgb_initial,
                "rgb_max": music_rgb_range["max"] if music_rgb_supported else None,
            }
            if music_rgb_supported and music_state["rgb_value"] is None:
                music_state["rgb_value"] = music_rgb_range["min"]

            self.upsert_state(device_id, music=music_state)

            if "music_mode" not in self.states.get(device_id, {}).get("select", {}):
                self.upsert_state(device_id, select={"music_mode": music_state["mode"]})
            if "music_sensitivity" not in self.states.get(device_id, {}).get("number", {}):
                self.upsert_state(device_id, number={"music_sensitivity": music_state["sensitivity"]})
            if music_auto_color_values and "music_auto_color" not in self.states.get(device_id, {}).get("switch", {}):
                self.upsert_state(device_id, switch={"music_auto_color": "ON" if music_state["auto_color_state"] else "OFF"})
            if music_rgb_supported and "music_rgb" not in self.states.get(device_id, {}).get("number", {}):
                self.upsert_state(device_id, number={"music_rgb": music_state["rgb_value"]})

        internal_updates: dict[str, Any] = {}
        if dynamic_scene_labels_internal:
            internal_updates["dynamic_scene_labels"] = dynamic_scene_labels_internal
        if dynamic_scene_instances_map:
            internal_updates["dynamic_scene_instances"] = dynamic_scene_instances_map
        if dynamic_scene_components_map:
            internal_updates["dynamic_scene_components"] = dynamic_scene_components_map
        if internal_updates:
            self.upsert_state(device_id, internal=internal_updates)

        return components

    async def prepare_device(self: Govee2Mqtt, device: dict[str, Any], raw_id: str, device_id: str, type: str) -> None:
        self.upsert_device(device_id, component=device)
        if "internal" not in self.states.get(device_id, {}):
            self.upsert_state(device_id, internal={"raw_id": raw_id, "sku": device["device"]["model"]})
        await self.build_device_states(device_id)

        if not self.is_discovered(device_id):
            self.logger.info(f'added new {type}: "{device["device"]["name"]}" [Govee {device["device"]["model"]}] ({self.get_device_name(device_id)})')
            await self.publish_device_discovery(device_id)

        await self.publish_device_availability(device_id, online=True)
        await self.publish_device_state(device_id)


def _build_device_payload(service: "Govee2Mqtt", device_id: str, source: dict[str, Any], domain: str, components: dict[str, Any]) -> dict[str, Any]:
    return {
        "stat_t": service.mqtt_helper.stat_t(device_id, domain),
        "avty_t": service.mqtt_helper.avty_t(device_id),
        "device": {
            "name": source["deviceName"],
            "identifiers": [
                service.mqtt_helper.device_slug(device_id),
            ],
            "manufacturer": "Govee",
            "model": source["sku"],
            "connections": [
                ["mac", source["device"]],
            ],
            "via_device": service.service,
        },
        "origin": {
            "name": service.service_name,
            "sw": service.config["version"],
            "support_url": "https://github.com/weirdTangent/govee2mqtt",
        },
        "qos": service.qos,
        "cmps": components,
    }
