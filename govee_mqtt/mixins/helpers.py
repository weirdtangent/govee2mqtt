from .._imports import *

import json
import os
import signal
import threading
from util import number_to_rgb, rgb_to_number, find_key_by_value

class HelpersMixin:

    def build_device_states(self, states, raw_id, sku):
        data = self.goveec.get_device(raw_id, sku)

        for key in data:
            if not data[key]:
                continue
            match key:
                case "online":
                    states["availability"] = "online" if data[key] else "offline"
                case 'powerSwitch':
                    states['light']['state'] = 'ON' if data[key] == 1 else 'OFF'
                case 'brightness':
                    states['light']['brightness'] = data[key]
                case 'colorRgb':
                    states['light']['rgb'] = number_to_rgb(data[key], states['light']['rgb_max'])
                case 'colorTemperatureK':
                    states['light']['color_temp'] = data[key]
                case 'gradientToggle':
                    states['switch']['gradient'] = 'on' if data[key] == 1 else 'off'
                case 'nightlightToggle':
                    states['switch']['nightlight'] = 'on' if data[key] == 1 else 'off'
                case 'dreamViewToggle':
                    states['switch']['dreamview'] = 'on' if data[key] == 1 else 'off'
                case 'sensorTemperature':
                    states['sensor']['temperature'] = data[key]
                case 'sensorHumidity':
                    states['sensor']['humidity'] = data[key]
                case 'musicMode':
                    if isinstance(data[key], dict):
                        if data['musicMode'] != "":
                            states['music']['mode'] = data['musicMode']
                        states['music']['sensitivity'] = data['sensitivity']
                    elif data[key] != '':
                        states['music']['mode'] = find_key_by_value(states['music']['options'], data[key])
                case 'sensitivity':
                    states['music']['sensitivity'] = data[key]
                case 'lastUpdate':
                    states.setdefault('meta', {})['last_update'] = (
                        data[key].strftime("%Y-%m-%d %H:%M:%S") if hasattr(data[key], "isoformat") else str(data[key])
                    )
                case 'lastUpdate':
                    states['state']['last_update'] = data[key].isoformat()
                case _:
                    self.logger.warning(f"Unhandled state {key} with value {data[key]} from Govee")

    # convert MQTT attributes to Govee capabilities
    def build_govee_capabilities(self, device_id, attributes):
        # Handle case where attributes was sent as a JSON string
        if isinstance(attributes, str):
            if attributes == 'ON' or attributes == 'OFF':
                attributes = {'light': attributes }
        elif not isinstance(attributes, dict):
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
        light = states.get('light', {})
        switch = states.get('switch', {})

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

                case "rgb":
                    rgb_val = rgb_to_number(value)
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
                    switch[key] = "on" if state_on else "off"
                    for other in {"gradient", "nightlight", "dreamview"} - {key}:
                        switch[other] = "off"
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
        if 'brightness' in capabilities and 'turn' in capabilities:
            del capabilities['turn']
        if 'color' in capabilities and 'turn' in capabilities:
            del capabilities['turn']

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

    def send_command(self, device_id, response):
        if device_id == 'service':
            self.logger.error(f'Why are you trying to send {response} to the "service"? Ignoring you.')
            return
        states = self.states.get(device_id, None)
        raw_id = self.get_raw_id(device_id)
        sku = self.get_device_sku(device_id)

        capabilities = self.build_govee_capabilities(device_id, response)
        if not capabilities:
            self.logger.debug(f'No set of capabilities built to send Govee for {device_id}')
            return

        need_boost = False
        for key in capabilities:
            response = self.goveec.send_command(raw_id, sku, capabilities[key]['type'], capabilities[key]['instance'], capabilities[key]['value'])
            self.publish_service_state()

            # no need to boost-refresh if we get the state back on the successful command response
            if len(response) > 0:
                self.build_device_states(states,raw_id,sku)

                # now that we've used the data, lets remove the chunky
                # `lastUpdate` key and then dump the rest into the log
                response.pop("lastUpdate", None)
                self.logger.debug(f'Got Govee response from command: {response}')

                self.publish_device_state(device_id)

                # remove from boosted list (if there), since we got a change
                if device_id in self.boosted:
                    self.boosted.remove(device_id)
            else:
                self.logger.info(f'Did not find changes in Govee response: {response}')
                need_boost = True

        # if we send a command and did not get a state change back on the response
        # lets boost this device to refresh it, just in case
        if need_boost and device_id not in self.boosted:
            self.boosted.append(device_id)

    def handle_service_message(self, handler, message):
        match handler:
            case "device_refresh":
                self.device_interval = message
            case 'device_list_refresh':
                self.device_list_interval = message
            case 'device_boost_refresh':
                self.device_boost_interval = message
            case "refresh_device_list":
                if message == "refresh":
                    self.rediscover_all()
                else:
                    self.logger.error('[handler] unknown [message]')
                    return
            case _:
                self.logger.error(f'Unrecognized message to {self.service_slug}: {attribute} -> {message}')
                return
        self.publish_service_state()

    def rediscover_all(self):
        self.publish_service_state()
        self.publish_service_discovery()
        for device_id in self.devices:
            if device_id == 'service': continue
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

