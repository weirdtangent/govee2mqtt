# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import os
import signal
import threading
from typing import Any, Dict
from deepmerge import Merger


class HelpersMixin:
    def refresh_device_states(self, device_id, data=None):
        if not data:
            data = self.get_device(
                self.get_raw_id(device_id), self.get_device_sku(device_id)
            )

        for key in data:
            if not data[key]:
                continue
            match key:
                case "online":
                    self.upsert_state(
                        device_id, availability="online" if data[key] else "offline"
                    )
                case "powerSwitch":
                    self.upsert_state(
                        device_id, light={"state": "ON" if data[key] == 1 else "OFF"}
                    )
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
                    )
                case "nightlightToggle":
                    self.upsert_state(
                        device_id,
                        switch={"nightlight": "ON" if data[key] == 1 else "OFF"},
                    )
                case "dreamViewToggle":
                    self.upsert_state(
                        device_id,
                        switch={"dreamview": "ON" if data[key] == 1 else "OFF"},
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
                    self.upsert_state(
                        device_id, last_update=data[key].strftime("%Y-%m-%d %H:%M:%S")
                    )
                case _:
                    self.logger.warning(
                        f"Unhandled state {key} with value {data[key]} from Govee"
                    )

    # convert MQTT attributes to Govee capabilities
    def build_govee_capabilities(
        self, device_id: str, attributes: dict[str, Any]
    ) -> Dict[str, dict]:
        # Handle case where attributes was sent as a JSON string
        # if isinstance(attributes, str):
        #     if attributes == "ON" or attributes == "OFF":
        #         attributes = {"light": attributes}
        if not isinstance(attributes, dict):
            try:
                attributes = json.loads(attributes)
            except json.JSONDecodeError:
                self.logger.warning(f"[HA] Invalid JSON for {device_id}: {attributes}")
                return {}

        if not isinstance(attributes, dict):
            self.logger.warning(
                f"[HA] Skipping unexpected capabilities format for {device_id}: {type(attributes).__name__}"
            )
            return {}

        states = self.states[device_id]
        light = states.get("light", {})
        switch = states.get("switch", {})

        capabilities = {}
        for key, value in attributes.items():

            match key:
                case "state" | "light":
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

                case "rgb" | "color":
                    rgb_val = self.rgb_to_number(value)
                    light["rgb_color"] = value
                    capabilities["colorRgb"] = {
                        "type": "devices.capabilities.color_setting",
                        "instance": "colorRgb",
                        "value": rgb_val,
                    }

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
                    if isinstance(attributes, dict) and "music_mode" in attributes:
                        mode = states["music"]["options"][attributes["music_mode"]]
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
                    sensitivity = attributes.get(
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
                    self.logger.warning(f"Ignored unknown attribute: {key} => {value}")

        # cannot send "turn" with either brightness or color
        if "brightness" in capabilities and "turn" in capabilities:
            del capabilities["turn"]
        if "color" in capabilities and "turn" in capabilities:
            del capabilities["turn"]

        return capabilities

    def _extract_scalar(self, val):
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

    def send_command(self, device_id, command: dict[str, Any]):
        if device_id == "service":
            self.logger.error(
                f'Why are you trying to send {command} to the "service"? Ignoring you.'
            )
            return

        # convert what we received in the command to Govee API capabilities
        capabilities = self.build_govee_capabilities(device_id, command)
        if not capabilities:
            self.logger.debug(
                f"Nothing to send Govee for {device_id} for command {command}"
            )
            return

        need_boost = False
        for key in capabilities:
            self.logger.debug(
                f"Posting {key} to Govee API: "
                + ", ".join(f"{k}={v}" for k, v in capabilities[key].items())
            )
            response = self.post_command(
                self.get_raw_id(device_id),
                self.get_device_sku(device_id),
                capabilities[key]["type"],
                capabilities[key]["instance"],
                capabilities[key]["value"],
            )
            self.publish_service_state()

            # no need to boost-refresh if we get the state back on the successful command response
            if len(response) > 0:
                self.refresh_device_states(device_id, response)
                self.logger.info(f"Got response from Govee API: {response}")
                self.publish_device_state(device_id)

                # remove from boosted list (if there), since we got a change
                if device_id in self.boosted:
                    self.boosted.remove(device_id)
            else:
                self.logger.info(f"No details in response from Govee API: {response}")
                need_boost = True

        # if we send a command and did not get a state change back on the response
        # lets boost this device to refresh it, just in case
        if need_boost and device_id not in self.boosted:
            self.boosted.append(device_id)

    def handle_service_message(self, handler, message):
        match handler:
            case "device_refresh":
                self.device_interval = message
            case "device_list_refresh":
                self.device_list_interval = message
            case "snapshot_refresh":
                self.device_boost_interval = message
            case "refresh_device_list":
                if message == "refresh":
                    self.rediscover_all()
                else:
                    self.logger.error("[handler] unknown [message]")
                    return
            case _:
                self.logger.error(
                    f"Unrecognized message to {self.service_slug}: {handler} with {message}"
                )
                return
        self.publish_service_state()

    def rediscover_all(self):
        self.publish_service_state()
        self.publish_service_discovery()
        for device_id in self.devices:
            if device_id == "service":
                continue
            self.publish_device_state(device_id)
            self.publish_device_discovery(device_id)

    # Utility functions ---------------------------------------------------------------------------

    def _install_signal_handlers(self):
        """Install very simple shutdown handlers (used in Docker)."""
        try:
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)
        except Exception:
            self.logger.debug("Signal handlers not supported on this platform")

    def _handle_signal(self, signum, frame=None):
        """Handle SIGTERM/SIGINT and exit cleanly or forcefully."""
        sig_name = signal.Signals(signum).name
        self.logger.warning(f"{sig_name} received - stopping service loop")
        self.running = False

        # Try saving state before timer kicks in
        try:
            self.save_state()
            self.logger.info("State saved after signal")
        except Exception as e:
            self.logger.warning(f"Failed to save state on signal: {e}")

        def _force_exit():
            self.logger.warning("Force-exiting process after signal")
            os._exit(0)

        threading.Timer(5.0, _force_exit).start()

    # Upsert devices and states -------------------------------------------------------------------

    MERGER = Merger(
        [(dict, "merge"), (list, "append_unique"), (set, "union")],
        ["override"],  # type conflicts: new wins
        ["override"],  # fallback
    )

    def upsert_device(
        self,
        key: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        rec = self.devices.setdefault(key, {})
        if fields:
            self.MERGER.merge(rec, fields)
        return rec

    def upsert_state(
        self,
        key: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        rec = self.states.setdefault(key, {})
        if fields:
            self.MERGER.merge(rec, fields)
        return rec
