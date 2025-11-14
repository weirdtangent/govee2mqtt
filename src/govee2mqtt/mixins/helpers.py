# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import colorsys
from deepmerge.merger import Merger
import logging
import os
import pathlib
import signal
import threading
from types import FrameType
import yaml

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt

READY_FILE = os.getenv("READY_FILE", "/tmp/govee2mqtt.ready")


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""

    pass


class HelpersMixin:
    async def build_device_states(self: Govee2Mqtt, device_id: str, data: dict[str, Any] = {}) -> None:
        if not data:
            data = await self.get_device(self.get_raw_id(device_id), self.get_device_sku(device_id))

        for key in data:
            if not data[key]:
                continue
            match key:
                case "online":
                    self.upsert_state(device_id, availability="online" if data[key] else "offline")
                case "powerSwitch":
                    self.upsert_state(device_id, light={"state": "ON" if data[key] == 1 else "OFF"})
                case "brightness":
                    self.upsert_state(device_id, light={"brightness": data[key]})
                case "colorRgb":
                    rgb_int = data[key]
                    self.upsert_state(
                        device_id,
                        light={
                            "rgb_color": [
                                (rgb_int >> 16) & 0xFF,
                                (rgb_int >> 8) & 0xFF,
                                rgb_int & 0xFF,
                            ]
                        },
                    )
                case "colorTemperatureK":
                    self.upsert_state(device_id, light={"color_temp": data[key]})
                case "gradientToggle":
                    self.upsert_state(
                        device_id,
                        switch={"gradient": "ON" if data[key] == 1 else "OFF"},
                        light={"light": "ON" if data[key] == 1 else "OFF"},
                    )
                case "nightlightToggle":
                    self.upsert_state(
                        device_id,
                        switch={"nightlight": "ON" if data[key] == 1 else "OFF"},
                        light={"light": "ON" if data[key] == 1 else "OFF"},
                    )
                case "dreamViewToggle":
                    self.upsert_state(
                        device_id,
                        switch={"dreamview": "ON" if data[key] == 1 else "OFF"},
                        light={"light": "ON" if data[key] == 1 else "OFF"},
                    )
                case "sensorTemperature":
                    self.upsert_state(device_id, sensor={"temperature": data[key]})
                case "sensorHumidity":
                    self.upsert_state(device_id, sensor={"humidity": data[key]})
                # case "musicMode":
                #     if isinstance(data[key], dict):
                #         if data["musicMode"] != "":
                #             states["music"]["mode"] = data["musicMode"]
                #         states["music"]["sensitivity"] = data["sensitivity"]
                #     elif data[key] != "":
                #         states["music"]["mode"] = self.find_key_by_value(
                #             states["music"]["options"], data[key]
                #         )
                # case "sensitivity":
                #     states["music"]["sensitivity"] = data[key]
                case "lastUpdate":
                    self.upsert_state(device_id, last_update=data[key].strftime("%Y-%m-%d %H:%M:%S"))
                case _:
                    self.logger.warning(f"Unhandled state {key} with value {data[key]} from Govee")

    # convert MQTT attributes to Govee capabilities
    def build_govee_capabilities(self: Govee2Mqtt, device_id: str, attribute: str, payload: Any) -> dict[str, dict]:
        states = self.states[device_id]
        light = states.get("light", {})
        switch = states.get("switch", {})

        if isinstance(payload, int | str | float):
            payload = {attribute: payload}

        capabilities: dict[str, Any] = {}
        for key, value in payload.items():

            match key:
                case "state" | "light" | "value":
                    state_on = str(value).lower() == "on"
                    light["state"] = "ON" if state_on else "OFF"
                    capabilities["powerSwitch"] = {
                        "type": "devices.capabilities.on_off",
                        "instance": "powerSwitch",
                        "value": 1 if state_on else 0,
                    }

                case "brightness":
                    light["brightness"] = int(value)
                    capabilities["brightness"] = {
                        "type": "devices.capabilities.range",
                        "instance": "brightness",
                        "value": int(value),
                    }

                case "rgb_color" | "rgb" | "color":
                    if isinstance(value, str):
                        value = list(map(int, value.split(",", 3)))
                    if isinstance(value, list) and len(value) == 3:
                        rgb_val = self.rgb_to_number(value)
                        light["rgb_color"] = value
                        capabilities["colorRgb"] = {
                            "type": "devices.capabilities.color_setting",
                            "instance": "colorRgb",
                            "value": rgb_val,
                        }
                    else:
                        self.logger.warning(f"Ignored unknown or invalid attribute: {key} => {value}")

                case "color_temp":
                    light["color_temp"] = int(value)
                    capabilities["colorTemperatureK"] = {
                        "type": "devices.capabilities.color_setting",
                        "instance": "colorTemperatureK",
                        "value": int(value),
                    }

                case "gradient" | "nightlight" | "dreamview":
                    state_on = str(value).lower() == "on"
                    switch[key] = "ON" if state_on else "OFF"
                    # if one mode turned ON the others must be OFF
                    for other in {"gradient", "nightlight", "dreamview"} - {key}:
                        switch[other] = "OFF"
                    capabilities[f"{key}Toggle"] = {
                        "type": "devices.capabilities.toggle",
                        "instance": f"{key}Toggle",
                        "value": 1 if state_on else 0,
                    }

                case "music_sensitivity":
                    mode = states["music"]["options"][states["music"]["mode"]]
                    if isinstance(payload, dict) and "music_mode" in payload:
                        mode = states["music"]["options"][payload["music_mode"]]
                    capabilities["musicMode"] = {
                        "type": "devices.capabilities.music_setting",
                        "instance": "musicMode",
                        "value": {
                            "musicMode": mode,
                            "sensitivity": value,
                        },
                    }

                case "music_mode":
                    mode = states["music"]["options"][value]
                    sensitivity = payload.get(
                        "music_sensitivity",
                        states["music"]["sensitivity"],
                    )
                    capabilities["musicMode"] = {
                        "type": "devices.capabilities.music_setting",
                        "instance": "musicMode",
                        "value": {
                            "musicMode": mode,
                            "sensitivity": sensitivity,
                        },
                    }

                case _:
                    self.logger.warning(f"Ignored unknown or invalid attribute: {key} => {value}")

        # cannot send "turn" with either brightness or color
        if "brightness" in capabilities and "turn" in capabilities:
            del capabilities["turn"]
        if "color" in capabilities and "turn" in capabilities:
            del capabilities["turn"]

        return capabilities

    def _extract_scalar(self: Govee2Mqtt, val: Any) -> Any:
        """Try to get a representative scalar from arbitrary API data."""
        # direct primitive
        if isinstance(val, (int, float, str, bool)):
            return val

        # dict: look for a likely scalar value
        if isinstance(val, dict):
            for v in val.values():
                if isinstance(v, (int, float, str, bool)):
                    return v
            return None

        # list: prefer first simple element
        if isinstance(val, list) and val:
            for v in val:
                if isinstance(v, (int, float, str, bool)):
                    return v
            return None

        return None

    # send command to Govee -----------------------------------------------------------------------

    async def send_command(self: Govee2Mqtt, device_id: str, attribute: str, command: Any) -> None:
        if device_id == "service":
            self.logger.error(f'Why are you trying to send {command} to the "service"? Ignoring you.')
            return

        # convert what we received in the command to Govee API capabilities
        capabilities = self.build_govee_capabilities(device_id, attribute, command)
        if not capabilities:
            self.logger.debug(f"Nothing to send Govee for {device_id} for command {command}")
            return

        need_boost = False
        for key in capabilities:
            self.logger.debug(f"Posting {key} to Govee API: " + ", ".join(f"{k}={v}" for k, v in capabilities[key].items()))
            response = await self.post_command(
                self.get_raw_id(device_id),
                self.get_device_sku(device_id),
                capabilities[key]["type"],
                capabilities[key]["instance"],
                capabilities[key]["value"],
            )
            await self.publish_service_state()

            # no need to boost-refresh if we get the state back on the successful command response
            if len(response) > 0:
                await self.build_device_states(device_id, response)
                self.logger.debug(f"Got response from Govee API: {response}")
                await self.publish_device_state(device_id)

                # remove from boosted list (if there), since we got a change
                if device_id in self.boosted:
                    self.boosted.remove(device_id)
            else:
                self.logger.debug(f"No details in response from Govee API: {response}")
                need_boost = True

        # if we send a command and did not get a state change back on the response
        # lets boost this device to refresh it, just in case
        if need_boost and device_id not in self.boosted:
            self.boosted.append(device_id)

    async def handle_service_message(self: Govee2Mqtt, handler: str, message: Any) -> None:
        match handler:
            case "refresh_interval":
                self.device_interval = int(message)
                self.logger.info(f"refresh_interval updated to be {message}")
            case "rescan_interval":
                self.device_list_interval = int(message)
                self.logger.info(f"rescan_interval updated to be {message}")
            case "boost_interval":
                self.device_boost_interval = int(message)
                self.logger.info(f"boost_interval updated to be {message}")
            case _:
                self.logger.error(f"Unrecognized message to {self.mqtt_helper.service_slug}: {handler} with {message}")
                return
        await self.publish_service_state()

    async def rediscover_all(self: Govee2Mqtt) -> None:
        await self.publish_service_state()
        await self.publish_service_discovery()
        for device_id in self.devices:
            await self.publish_device_state(device_id)
            await self.publish_device_discovery(device_id)

    # Utility functions ---------------------------------------------------------------------------

    def _handle_signal(self: Govee2Mqtt, signum: int, frame: FrameType | None = None) -> None:
        sig_name = signal.Signals(signum).name
        self.logger.warning(f"{sig_name} received - stopping service loop")
        self.running = False

        # Try saving state before timer kicks in
        try:
            self.save_state()
            self.logger.info("State saved after signal")
        except Exception as e:
            self.logger.warning(f"Failed to save state on signal: {e}")

        def _force_exit() -> None:
            self.logger.warning("Force-exiting process after signal")
            os._exit(0)

        threading.Timer(5.0, _force_exit).start()

    def mark_ready(self: Govee2Mqtt) -> None:
        pathlib.Path(READY_FILE).touch()

    def heartbeat_ready(self: Govee2Mqtt) -> None:
        pathlib.Path(READY_FILE).touch()

    def read_file(self: Govee2Mqtt, file_name: str) -> str:
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                return file.read().strip()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_name}")

    def number_to_rgb_linear(self: Govee2Mqtt, number: int, max_value: int) -> dict[str, int]:
        if max_value is None or max_value <= 0:
            raise ValueError("max_value must be > 0")
        t = max(0.0, min(1.0, number / max_value))
        r = int(255 * (1.0 - t))  # or round(...) if you prefer 128 at 50%
        g = int(255 * t)
        b = 0
        return {"r": r, "g": g, "b": b}

    def number_to_rgb_hsv(self: Govee2Mqtt, number: int, max_value: int, value: float = 1.0, saturation: float = 1.0) -> dict[str, int]:
        # value & saturation are 0.0–1.0; many bulbs like value tied to the brightness slider
        if max_value is None or max_value <= 0:
            raise ValueError("max_value must be > 0")
        t = max(0.0, min(1.0, number / max_value))
        hue = (1.0 / 3.0) * t  # 0=red, 1/3=green
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
        return {
            "r": int(round(r * 255)),
            "g": int(round(g * 255)),
            "b": int(round(b * 255)),
        }

    def number_to_rgb_bluepop(self: Govee2Mqtt, number: int, max_value: int, brightness: int = 255) -> dict[str, int]:
        # brightness: 0–255 cap applied AFTER color math
        if max_value is None or max_value <= 0:
            raise ValueError("max_value must be > 0")
        t = max(0.0, min(1.0, number / max_value))

        r = 255 * (1.0 - t)
        g = 255 * t
        b = 255 * (1.0 - abs(2.0 * t - 1.0))  # triangle peaking at midpoint

        # normalize to desired brightness by scaling so the max channel == brightness
        m = max(r, g, b, 1e-6)
        scale = brightness / m
        r, g, b = int(round(r * scale)), int(round(g * scale)), int(round(b * scale))
        return {"r": r, "g": g, "b": b}

    def rgb_to_number(self: Govee2Mqtt, rgb: list[int] | dict[str, int]) -> int:
        try:
            if isinstance(rgb, (list, tuple)):
                r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            elif isinstance(rgb, dict):
                r = int(rgb.get("r", 0))
                g = int(rgb.get("g", 0))
                b = int(rgb.get("b", 0))
            return (r << 16) | (g << 8) | b
        except Exception as e:
            raise ValueError(f"Invalid RGB value: {rgb!r}") from e

    def find_key_by_value(self: Govee2Mqtt, d: dict[str, Any], target: str) -> Any:
        return next((k for k, v in d.items() if v == target), None)

    def load_config(self: Govee2Mqtt, config_arg: Any | None = None) -> dict[str, Any]:
        version = os.getenv("APP_VERSION", self.read_file("VERSION"))
        tier = os.getenv("APP_TIER", "prod")
        if tier == "dev":
            version += ":DEV"

        config_from = "env"
        config: dict[str, str | bool | int | dict] = {}

        # Determine config file path
        config_path = config_arg or "/config"
        config_path = os.path.expanduser(config_path)
        config_path = os.path.abspath(config_path)

        if os.path.isdir(config_path):
            config_file = os.path.join(config_path, "config.yaml")
        elif os.path.isfile(config_path):
            config_file = config_path
            config_path = os.path.dirname(config_file)
        else:
            # If it's not a valid path but looks like a filename, handle gracefully
            if config_path.endswith(".yaml"):
                config_file = config_path
            else:
                config_file = os.path.join(config_path, "config.yaml")

        # Try to load from YAML
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = yaml.safe_load(f) or {}
                config_from = "file"
            except Exception as e:
                logging.warning(f"Failed to load config from {config_file}: {e}")
        else:
            logging.warning(f"Config file not found at {config_file}, falling back to environment vars")

        # Merge with environment vars (env vars override nothing if file exists)
        mqtt = cast(dict[str, Any], config.get("mqtt", {}))
        govee = cast(dict[str, Any], config.get("govee", {}))

        # fmt: off
        mqtt = {
              "host":         cast(str, mqtt.get("host"))            or os.getenv("MQTT_HOST", "localhost"),
              "port":     int(cast(str, mqtt.get("port")             or os.getenv("MQTT_PORT", 1883))),
              "qos":      int(cast(str, mqtt.get("qos")              or os.getenv("MQTT_QOS", 0))),
              "username":               mqtt.get("username")         or os.getenv("MQTT_USERNAME", ""),
              "password":               mqtt.get("password")         or os.getenv("MQTT_PASSWORD", ""),
              "tls_enabled":            mqtt.get("tls_enabled")      or (os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"),
              "tls_ca_cert":            mqtt.get("tls_ca_cert")      or os.getenv("MQTT_TLS_CA_CERT"),
              "tls_cert":               mqtt.get("tls_cert")         or os.getenv("MQTT_TLS_CERT"),
              "tls_key":                mqtt.get("tls_key")          or os.getenv("MQTT_TLS_KEY"),
              "prefix":                 mqtt.get("prefix")           or os.getenv("MQTT_PREFIX", "govee2mqtt"),
              "discovery_prefix":       mqtt.get("discovery_prefix") or os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        }

        govee = {
            "api_key":                   govee.get("api_key") or os.getenv("GOVEE_API_KEY"),
            "device_interval":       int(cast(str, govee.get("device_interval") or os.getenv("GOVEE_DEVICE_INTERVAL", 30))),
            "device_boost_interval": int(cast(str, govee.get("device_boost_interval") or os.getenv("GOVEE_DEVICE_BOOST_INTERVAL", 5))),
            "device_list_interval":  int(cast(str, govee.get("device_list_interval") or os.getenv("GOVEE_LIST_INTERVAL", 3600))),
        }

        config = {
            "mqtt":        mqtt,
            "govee":       govee,
            "debug":       str(config.get("debug") or os.getenv("DEBUG", "")).lower() == "true",
            "timezone":    config.get("timezone", os.getenv("TZ", "UTC")),
            "config_from": config_from,
            "config_path": config_path,
            "version":     version,
        }
        # fmt: on

        # Validate required fields
        if not cast(dict, config["govee"]).get("api_key"):
            raise ConfigError("`govee.api_key` required in config file or GOVEE_API_KEY env var")
        if not cast(dict, config["mqtt"]).get("host"):
            raise ConfigError("`mqtt host` value is missing, not even the default value")
        if not cast(dict, config["mqtt"]).get("port"):
            raise ConfigError("`mqtt port` value is missing, not even the default value")

        return config

    # Upsert devices and states -------------------------------------------------------------------

    def _assert_no_tuples(self: Govee2Mqtt, data: Any, path: str = "root") -> None:
        if isinstance(data, tuple):
            raise TypeError(f"⚠️ Found tuple at {path}: {data!r}")

        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(key, tuple):
                    raise TypeError(f"⚠️ Found tuple key at {path}: {key!r}")
                self._assert_no_tuples(value, f"{path}.{key}")
        elif isinstance(data, list):
            for idx, value in enumerate(data):
                self._assert_no_tuples(value, f"{path}[{idx}]")

    def upsert_device(self: Govee2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool | None) -> bool:
        MERGER = Merger(
            [(dict, "merge"), (list, "append_unique"), (set, "union")],
            ["override"],
            ["override"],
        )
        prev = self.devices.get(device_id, {})
        for section, data in kwargs.items():
            self._assert_no_tuples(data, f"device[{device_id}].{section}")
            merged = MERGER.merge(self.devices.get(device_id, {}), {section: data})
            self._assert_no_tuples(merged, f"device[{device_id}].{section} (post-merge)")
            self.devices[device_id] = merged
        new = self.devices.get(device_id, {})
        return False if prev == new else True

    def upsert_state(self: Govee2Mqtt, device_id: str, **kwargs: dict[str, Any] | str | int | bool | None) -> bool:
        MERGER = Merger(
            [(dict, "merge"), (list, "append_unique"), (set, "union")],
            ["override"],
            ["override"],
        )
        prev = self.states.get(device_id, {})
        for section, data in kwargs.items():
            self._assert_no_tuples(data, f"state[{device_id}].{section}")
            merged = MERGER.merge(self.states.get(device_id, {}), {section: data})
            self._assert_no_tuples(merged, f"state[{device_id}].{section} (post-merge)")
            self.states[device_id] = merged
        new = self.states.get(device_id, {})
        return False if prev == new else True
