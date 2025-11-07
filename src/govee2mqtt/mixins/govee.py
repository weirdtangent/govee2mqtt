# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import re

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class GoveeMixin:
    async def refresh_device_list(self: Govee2Mqtt) -> None:
        self.logger.info(f"Refreshing device list from Govee (every {self.device_list_interval} sec)")

        govee_devices = self.get_device_list()
        if not govee_devices:
            return
        self.publish_service_state()

        seen_devices = set()

        for device in govee_devices:
            created = self.build_component(device)
            if created:
                seen_devices.add(created)

        # Mark missing devices offline
        missing_devices = set(self.devices.keys()) - seen_devices
        for device_id in missing_devices:
            self.publish_device_availability(device_id, online=False)
            self.logger.warning(f"Device {device_id} not seen in Govee API list — marked offline")

        # Handle first discovery completion
        if not self.discovery_complete:
            await asyncio.sleep(5)
            self.rediscover_all()
            self.logger.info("First-time device setup and discovery is done")
            self.discovery_complete = True

    # convert Govee device capabilities into MQTT components
    def build_component(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        device_class = self.classify_device(device)
        match device_class:
            case "light":
                return self.build_light(device)
            case "sensor":
                return self.build_sensor(device)
        return ""

    def classify_device(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        sku = device["sku"]

        # lights are H6xxx, H7xxx, H8xxx
        if re.compile(r"^H[678]\d{3,}$").match(sku):
            return "light"
        # sensors are H5xxx
        if re.compile(r"^H5\d{3,}$").match(sku):
            return "sensor"

        # If we reach here, it's unsupported — log details for future handling
        device_name = device.get("deviceName", "Unknown Device")
        device_id = device.get("device", "Unknown ID")

        self.logger.debug(f'Unrecognized Govee device type: "{device_name}" [{sku}] ({device_id})')

        return ""

    def build_light(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        raw_id = cast(str, device["device"])
        device_id = raw_id.replace(":", "").upper()
        self.devices.setdefault(device_id, {})

        device_block = self.mqtt_helper.device_block(
            device["deviceName"],
            self.mqtt_helper.device_slug(device_id),
            device["sku"],
        )

        component = {
            "component_type": "light",
            "name": device["deviceName"],
            "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "light"),
            "stat_t": self.mqtt_helper.stat_t(device_id, "light"),
            "state_value_template": "{{ value_json.state | upper }}",
            "avty_t": self.mqtt_helper.avty_t(device_id),
            "cmd_t": self.mqtt_helper.cmd_t(device_id, "light"),
            "supported_color_modes": ["onoff"],
            "device": device_block,
        }
        self.upsert_state(
            device_id,
            internal={"raw_id": raw_id, "sku": device.get("sku", None)},
            light={},
        )
        modes = {}

        for cap in device["capabilities"]:
            match cap["instance"]:
                case "brightness":
                    component["supported_color_modes"].append("brightness")
                    component["brightness_scale"] = cap["parameters"]["range"]["max"]
                    component["brightness_state_topic"] = self.mqtt_helper.stat_t(device_id, "light")
                    component["brightness_value_template"] = "{{ value_json.brightness }}"
                    component["brightness_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light")
                    component["brightness_command_template"] = '{"brightness": {{ value }}}'
                    self.upsert_state(device_id, light={"brightness": 0})
                case "powerSwitch":
                    component["supported_color_modes"].append("onoff")
                case "colorRgb":
                    component["supported_color_modes"].append("rgb")
                    component["rgb_state_topic"] = self.mqtt_helper.stat_t(device_id, "light")
                    component["rgb_value_template"] = "{{ value_json.rgb_color | join(',') }}"
                    component["rgb_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light")
                    component["rgb_command_template"] = '{"rgb": [{{ value }}] }'
                    self.upsert_state(
                        device_id,
                        light={"rgb_max": cap["parameters"]["range"]["max"] or 16777215},
                    )
                case "colorTemperatureK":
                    component["supported_color_modes"].append("color_temp")
                    component["color_temp_kelvin"] = True
                    component["color_temp_state_topic"] = self.mqtt_helper.stat_t(device_id, "light")
                    component["color_temp_value_template"] = "{{ value_json.color_temp }}"
                    component["color_temp_command_topic"] = self.mqtt_helper.cmd_t(device_id, "light")
                    component["color_temp_command_template"] = '{"color_temp": {{ value }}}'
                    component["min_kelvin"] = cap["parameters"]["range"]["min"] or 2000
                    component["max_kelvin"] = cap["parameters"]["range"]["max"] or 9000
                    self.upsert_state(device_id, light={"color_temp": 0})
                case "gradientToggle":
                    modes["gradient"] = {
                        "component_type": "switch",
                        "name": f"{device['deviceName']} Gradient",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "gradient"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch"),
                        "state_value_template": "{{ value_json.gradient }}",
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "gradient"),
                        "avty_t": self.mqtt_helper.avty_t(device_id, "light"),
                        "avty_tpl": "{{ value_json.availability }}",
                        "icon": ("mdi:gradient-horizontal" if device["sku"] == "H6042" else "mdi:gradient-vertical"),
                        "via_device": self.mqtt_helper.service_slug,
                        "device": device_block,
                    }
                    self.upsert_state(device_id, switch={"gradient": "OFF"})

                case "nightlightToggle":
                    modes["nightlight"] = {
                        "component_type": "switch",
                        "name": f"{device['deviceName']} Nightlight",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "nightlight"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "nightlight"),
                        "state_value_template": "{{ value_json.nightlight }}",
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "nightlight"),
                        "avty_t": self.mqtt_helper.avty_t(device_id),
                        "icon": "mdi:weather-night",
                        "via_device": self.mqtt_helper.service_slug,
                        "device": device_block,
                    }
                    self.upsert_state(device_id, switch={"nightlight": "OFF"})

                case "dreamViewToggle":
                    modes["dreamview"] = {
                        "component_type": "switch",
                        "name": f"{device['deviceName']} Dreamview",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "dreamview"),
                        "stat_t": self.mqtt_helper.stat_t(device_id, "switch", "dreamview"),
                        "state_value_template": "{{ value_json.dreamview }}",
                        "cmd_t": self.mqtt_helper.cmd_t(device_id, "switch", "dreamview"),
                        "avty_t": self.mqtt_helper.avty_t(device_id),
                        "icon": "mdi:creation",
                        "via_device": self.mqtt_helper.service_slug,
                        "device": device_block,
                    }
                    self.upsert_state(device_id, switch={"dreamview": "OFF"})

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

        # If a color mode (rgb or color_temp) is supported, drop simpler modes
        modeset = set(component["supported_color_modes"])
        if "rgb" in modeset or "color_temp" in modeset:
            modeset.discard("onoff")
            modeset.discard("brightness")
            component.pop("brightness_scale", None)
            component.pop("brightness_state_topic", None)
            component.pop("brightness_value_template", None)
            component.pop("brightness_command_topic", None)
            component.pop("brightness_command_template", None)
        component["supported_color_modes"] = list(modeset)

        # watch for capabilities we don't handle
        unsupported = [
            cap["instance"]
            for cap in device["capabilities"]
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
        if unsupported:
            self.logger.debug(f'Unhandled light capabilities for {device["deviceName"]}: {unsupported}')

        # # if we ended up with no fancy way to command the light, add a simple way
        # if not any(
        #     x in component
        #     for x in [
        #         "brightness_command_topic",
        #         "rgb_command_topic",
        #         "color_temp_command_topic",
        #     ]
        # ):
        #     # fallback for simple on/off devices
        #     component["command_topic"] = self.mqtt_helper.cmd_t(device_id, "light")

        # insert, or update anything that changed, but don't lose anything
        self.upsert_device(device_id, component=component, modes=modes)

        self.refresh_device_states(device_id)

        if not self.is_discovered(device_id):
            self.logger.info(f'Added new light: "{device["deviceName"]}" [Govee {device["sku"]}] ({device_id})')

        self.publish_device_discovery(device_id)
        self.publish_device_availability(device_id, online=True)
        self.publish_device_state(device_id)

        return device_id

    def build_sensor(self: Govee2Mqtt, device: dict[str, Any]) -> str:
        raw_id = device["device"]
        parent = raw_id.replace(":", "").upper()

        for cap in device["capabilities"]:
            device_id = None
            component = None
            match cap["instance"]:
                case "sensorTemperature":
                    device_id = f"{parent}_t"
                    component = {
                        "component_type": "sensor",
                        "name": "Temperature",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "temperature"),
                        "device_class": "temperature",
                        "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                        "value_template": "{{ value_json.temperature | float }}",
                        "avty_t": self.mqtt_helper.avty_t(parent, "sensor"),
                        "avty_tpl": "{{ value_json.availability }}",
                        "state_class": "measurement",
                        "pl_avail": "online",
                        "pl_not_avail": "offline",
                        "unit_of_measurement": "°F",
                        "icon": "mdi:thermometer",
                        "device": self.mqtt_helper.device_block(
                            device["deviceName"],
                            self.mqtt_helper.device_slug(parent),
                            device["sku"],
                        ),
                    }

                case "sensorHumidity":
                    device_id = f"{parent}_h"
                    component = {
                        "component_type": "sensor",
                        "name": "Humidity",
                        "uniq_id": self.mqtt_helper.dev_unique_id(device_id, "humidity"),
                        "device_class": "humidity",
                        "stat_t": self.mqtt_helper.stat_t(parent, "sensor"),
                        "value_template": "{{ value_json.humidity | float }}",
                        "avty_t": self.mqtt_helper.avty_t(parent, "sensor"),
                        "avty_tpl": "{{ value_json.availability }}",
                        "state_class": "measurement",
                        "pl_avail": "online",
                        "pl_not_avail": "offline",
                        "unit_of_measurement": "%",
                        "icon": "mdi:water-percent",
                        "via_device": self.mqtt_helper.service_slug,
                        "device": self.mqtt_helper.device_block(
                            device["deviceName"],
                            self.mqtt_helper.device_slug(parent),
                            device["sku"],
                        ),
                    }
                case _:
                    continue

            if device_id:
                # insert, or update anything that changed, but don't lose anything
                self.upsert_device(device_id, component=component)
                self.upsert_state(
                    device_id,
                    internal={"raw_id": raw_id, "sku": device.get("sku", None)},
                    sensor={},
                )
                self.refresh_device_states(device_id)

                if not self.is_discovered(device_id):
                    self.logger.info(f'Added new sensor: "{component["name"]}" [Govee {device["sku"]}] ({device_id})')

                self.publish_device_discovery(device_id)
                self.publish_device_availability(device_id, online=True)
                self.publish_device_state(device_id)
                return device_id

        return ""
