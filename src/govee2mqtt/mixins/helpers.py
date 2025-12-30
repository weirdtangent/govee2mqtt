# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio
import colorsys
from deepmerge.merger import Merger
import logging
import os
import pathlib
import re
import signal
import threading
from types import FrameType
import yaml

from typing import TYPE_CHECKING, Any, Mapping, cast

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt

READY_FILE = os.getenv("READY_FILE", "/tmp/govee2mqtt.ready")

# Time window (in seconds) to batch commands for the same device.
# Home Assistant may send rgb_color and color_temp nearly simultaneously;
# we collect them and keep only the one that arrived last.
COLOR_MODE_BATCH_WINDOW = 0.1


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""

    pass


class HelpersMixin:
    async def build_device_states(self: Govee2Mqtt, device_id: str, data: dict[str, Any] = {}) -> None:
        if not data:
            data = await self.get_device(device_id)
        component = self.devices[device_id]["component"]

        for key in data:
            if not data[key]:
                continue

            match key:
                case "online":
                    self.upsert_state(device_id, availability="online" if data[key] else "offline")

                case "powerSwitch":
                    if "power" in component["cmps"]:
                        self.upsert_state(device_id, switch={"power": "ON" if data[key] == 1 else "OFF"})
                    elif "light" in component["cmps"]:
                        self.upsert_state(device_id, light={"state": "ON" if data[key] == 1 else "OFF"})

                case "brightness":
                    self.upsert_state(device_id, light={"brightness": data[key]})

                case "humidity":
                    self.upsert_state(device_id, number={"humidity": int(data[key])})

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
                    # restrict color_temp to be >= min and <= max
                    value = data[key]
                    if isinstance(value, str):
                        value = int(value)
                    color = min(max(value, component["cmps"]["light"]["min_kelvin"]), component["cmps"]["light"]["max_kelvin"])
                    self.upsert_state(device_id, light={"color_temp": color})

                case "gradientToggle":
                    self.upsert_state(device_id, switch={"gradient": "ON" if data[key] == 1 else "OFF"}, light={"state": "ON" if data[key] == 1 else "OFF"})

                case "nightlightToggle":
                    self.upsert_state(device_id, light={"state": "ON" if data[key] == 1 else "OFF"})

                case "warmMistToggle":
                    self.upsert_state(device_id, switch={"warm_mist": "ON" if data[key] == 1 else "OFF"})

                case "nightlightScene":
                    scene_value = data[key]
                    internal = self.states.get(device_id, {}).get("internal", {})
                    scene_labels = internal.get("nightlight_scene_labels", {})
                    scene_selection: str | None = None
                    if isinstance(scene_value, int):
                        scene_selection = scene_labels.get(scene_value) or scene_labels.get(str(scene_value))
                    elif isinstance(scene_value, str):
                        scene_selection = scene_labels.get(scene_value)
                    if not scene_selection and scene_value is not None:
                        scene_selection = str(scene_value)
                    if scene_selection:
                        self.upsert_state(device_id, select={"nightlight_scene": scene_selection})

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

                case "filterLifeTime":
                    lifetime_value: Any = data[key]
                    if isinstance(lifetime_value, dict):
                        lifetime_value = lifetime_value.get("value") or lifetime_value.get("percent")
                    if isinstance(lifetime_value, str):
                        stripped = lifetime_value.strip()
                        if stripped.replace(".", "", 1).isdigit():
                            lifetime_value = float(stripped) if "." in stripped else int(stripped)
                        else:
                            lifetime_value = stripped
                    if lifetime_value is not None:
                        self.upsert_state(device_id, sensor={"filter_life": lifetime_value})

                case "airQuality":
                    air_quality_value: Any = data[key]
                    if isinstance(air_quality_value, dict):
                        air_quality_value = air_quality_value.get("value") or air_quality_value.get("level") or air_quality_value.get("name")
                    if isinstance(air_quality_value, str):
                        air_quality_value = air_quality_value.strip()
                    if air_quality_value is not None:
                        self.upsert_state(device_id, sensor={"air_quality": air_quality_value})

                case "workMode":
                    work_mode_data = data[key]
                    if not isinstance(work_mode_data, dict):
                        continue
                    internal = self.states.get(device_id, {}).get("internal", {})
                    work_mode_labels = internal.get("work_mode_value_labels", {})
                    manual_level_labels = internal.get("manual_level_labels", {})
                    gear_mode_labels = internal.get("gear_mode_labels", {})
                    work_mode_selection: str | None = None

                    mode_value = work_mode_data.get("workMode")
                    if isinstance(mode_value, int):
                        mode_name = work_mode_labels.get(mode_value) or work_mode_labels.get(str(mode_value))
                        if isinstance(mode_name, str):
                            mode_name_lower = mode_name.lower()
                            requires_submode = mode_name_lower in {"manual", "gearmode"}
                            label_lookup: dict[int | str, str] | None = None
                            if mode_name_lower == "manual" and manual_level_labels:
                                label_lookup = manual_level_labels
                            elif mode_name_lower == "gearmode" and gear_mode_labels:
                                label_lookup = gear_mode_labels
                            if requires_submode and label_lookup:
                                raw_mode_value = work_mode_data.get("modeValue")
                                mode_specific_value_int = self._normalize_mode_numeric_value(raw_mode_value)
                                if mode_specific_value_int is None and isinstance(raw_mode_value, str):
                                    reverse_lookup = self.find_key_by_value(label_lookup, raw_mode_value)
                                    if reverse_lookup is not None:
                                        try:
                                            mode_specific_value_int = int(reverse_lookup)
                                        except (TypeError, ValueError):
                                            mode_specific_value_int = None
                                if mode_specific_value_int is not None:
                                    fallback = (
                                        f"Mist Level {mode_specific_value_int}" if mode_name_lower == "manual" else f"Gear Level {mode_specific_value_int}"
                                    )
                                    work_mode_selection = (
                                        label_lookup.get(mode_specific_value_int) or label_lookup.get(str(mode_specific_value_int)) or fallback
                                    )
                                elif isinstance(raw_mode_value, str):
                                    work_mode_selection = raw_mode_value
                            elif not requires_submode:
                                work_mode_selection = mode_name
                    elif isinstance(mode_value, str):
                        work_mode_selection = mode_value

                    if work_mode_selection:
                        self.upsert_state(device_id, select={"work_mode": work_mode_selection})

                case "modeValue":
                    if "work_mode" not in component["cmps"]:
                        continue
                    internal = self.states.get(device_id, {}).get("internal", {})
                    manual_level_labels = internal.get("manual_level_labels", {})
                    gear_mode_labels = internal.get("gear_mode_labels", {})
                    level_value = self._normalize_mode_numeric_value(data[key])
                    if level_value is None:
                        continue

                    level_selection = manual_level_labels.get(level_value) or manual_level_labels.get(str(level_value))
                    if not level_selection and gear_mode_labels:
                        level_selection = gear_mode_labels.get(level_value) or gear_mode_labels.get(str(level_value))
                    if not level_selection:
                        if manual_level_labels and not gear_mode_labels:
                            level_selection = f"Mist Level {level_value}"
                        elif gear_mode_labels and not manual_level_labels:
                            level_selection = f"Gear Level {level_value}"
                        elif manual_level_labels:
                            level_selection = f"Mist Level {level_value}"
                        elif gear_mode_labels:
                            level_selection = f"Gear Level {level_value}"
                        else:
                            level_selection = str(level_value)
                    self.upsert_state(device_id, select={"work_mode": level_selection})
                case key if key in {"lightScene", "diyScene", "snapshot"}:
                    internal = self.states.get(device_id, {}).get("internal", {})
                    value = data[key]
                    api_scene_handled = False

                    # Handle API-fetched light scenes (stored in light_scene_values)
                    if key == "lightScene":
                        light_scene_values = internal.get("light_scene_values", {})
                        if light_scene_values:
                            # Find scene name by matching the value (which could be {paramId, id} dict or int)
                            light_scene_selection: str | None = None
                            for scene_name, scene_value in light_scene_values.items():
                                if scene_value == value:
                                    light_scene_selection = scene_name
                                    break
                                # Check if both are dicts with matching id
                                if isinstance(value, dict) and isinstance(scene_value, dict):
                                    if value.get("id") == scene_value.get("id"):
                                        light_scene_selection = scene_name
                                        break
                                # Check if value is an int matching the id in a stored dict
                                if isinstance(value, int) and isinstance(scene_value, dict):
                                    if value == scene_value.get("id"):
                                        light_scene_selection = scene_name
                                        break
                                # Check if value is a dict with id matching a stored int
                                if isinstance(value, dict) and isinstance(scene_value, int):
                                    if value.get("id") == scene_value:
                                        light_scene_selection = scene_name
                                        break
                            if light_scene_selection:
                                self.upsert_state(device_id, select={"light_scene": light_scene_selection})
                                api_scene_handled = True

                    # Handle dynamic scenes from device capabilities (existing flow)
                    # Skip for lightScene if API scenes were already handled to avoid overwriting
                    if key == "lightScene" and api_scene_handled:
                        continue
                    scene_instances = internal.get("dynamic_scene_instances", {})
                    scene_labels_root = internal.get("dynamic_scene_labels", {})
                    component_key = scene_instances.get(key)
                    if not component_key:
                        continue
                    scene_labels = scene_labels_root.get(key, {})
                    dynamic_scene_selection: str | None = None
                    if isinstance(value, int):
                        dynamic_scene_selection = scene_labels.get(value) or scene_labels.get(str(value))
                    elif isinstance(value, str):
                        dynamic_scene_selection = scene_labels.get(value) or value
                    if not dynamic_scene_selection and value is not None:
                        dynamic_scene_selection = str(value)
                    if dynamic_scene_selection:
                        self.upsert_state(device_id, select={component_key: dynamic_scene_selection})
                case "segmentedBrightness":
                    value = data[key]
                    if not isinstance(value, dict):
                        continue
                    segments = value.get("segment")
                    brightness_value = value.get("brightness")
                    if not isinstance(segments, list) or not segments:
                        continue
                    try:
                        segment_id = int(segments[0])
                    except (TypeError, ValueError):
                        continue
                    if isinstance(brightness_value, (int, float)):
                        brightness_int = int(brightness_value)
                    else:
                        continue
                    segment_label = self._segment_option_label(segment_id)
                    self.upsert_state(
                        device_id,
                        segments={"selected_segment": segment_id, "brightness": brightness_int},
                        select={"segment_index": segment_label},
                        number={"segment_brightness": brightness_int},
                    )
                case "segmentedColorRgb":
                    value = data[key]
                    if not isinstance(value, dict):
                        continue
                    segments = value.get("segment")
                    rgb_value = value.get("rgb")
                    if not isinstance(segments, list) or not segments:
                        continue
                    try:
                        segment_id = int(segments[0])
                    except (TypeError, ValueError):
                        continue
                    rgb_int = self._normalize_music_rgb(rgb_value)
                    if rgb_int is None:
                        continue
                    segment_label = self._segment_option_label(segment_id)
                    self.upsert_state(
                        device_id,
                        segments={"selected_segment": segment_id, "rgb_value": rgb_int},
                        select={"segment_index": segment_label},
                        number={"segment_rgb": rgb_int},
                    )
                case "musicMode":
                    music_data = data[key]
                    if not isinstance(music_data, dict):
                        continue
                    component_music = component["cmps"]
                    music_state = self.states.get(device_id, {}).get("music", {})
                    if not music_state:
                        continue

                    music_updates: dict[str, Any] = {}
                    select_updates: dict[str, str] = {}
                    number_updates: dict[str, int] = {}
                    switch_updates: dict[str, str] = {}

                    options = music_state.get("options", {})
                    mode_value = music_data.get("musicMode")
                    music_mode_name: str | None = None
                    if isinstance(mode_value, int):
                        music_mode_name = self.find_key_by_value(options, mode_value)
                    elif isinstance(mode_value, str):
                        music_mode_name = mode_value
                    if music_mode_name:
                        music_updates["mode"] = music_mode_name
                        if "music_mode" in component_music:
                            select_updates["music_mode"] = music_mode_name

                    sensitivity_value = music_data.get("sensitivity")
                    if isinstance(sensitivity_value, (int, float)):
                        sensitivity_int = int(sensitivity_value)
                        music_updates["sensitivity"] = sensitivity_int
                        if "music_sensitivity" in component_music:
                            number_updates["music_sensitivity"] = sensitivity_int

                    auto_color_value = music_data.get("autoColor")
                    auto_color_state = self._normalize_music_auto_color_state(auto_color_value, music_state.get("auto_color_values", {}))
                    if auto_color_state is not None:
                        music_updates["auto_color_state"] = auto_color_state
                        if "music_auto_color" in component_music:
                            switch_updates["music_auto_color"] = "ON" if auto_color_state else "OFF"

                    rgb_value = music_data.get("rgb")
                    rgb_int = self._normalize_music_rgb(rgb_value, music_state.get("rgb_max"))
                    if rgb_int is not None:
                        music_updates["rgb_value"] = rgb_int
                        if "music_rgb" in component_music:
                            number_updates["music_rgb"] = rgb_int

                    if music_updates:
                        self.upsert_state(device_id, music=music_updates)
                    if select_updates:
                        self.upsert_state(device_id, select=select_updates)
                    if number_updates:
                        self.upsert_state(device_id, number=number_updates)
                    if switch_updates:
                        self.upsert_state(device_id, switch=switch_updates)

                # Handle scene-related numeric state IDs returned by Govee
                # When a scene is set (e.g., "Morning"), Govee returns both:
                #   - The complete scene via "lightScene" key (already handled above)
                #   - Individual components via "id" and "paramId" keys (handled here)
                # Example: Setting "Morning" → lightScene: {id: 1623, paramId: 1698}
                #                            → id: 1623, paramId: 1698 (separate keys)
                case "id" | "paramId":
                    # Get current internal state
                    internal = self.states.get(device_id, {}).get("internal", {})

                    # Store the scene component for debugging/validation
                    internal_key = f"scene_{key}"  # "scene_id" or "scene_paramId"
                    internal[internal_key] = data[key]

                    # Update internal state
                    self.upsert_state(device_id, internal=internal)

                    # Debug log to track scene state updates
                    self.logger.debug(f"Device '{self.get_device_name(device_id)}' scene {key} => {data[key]}")

                    # Validate scene ID matches the current scene (if set)
                    if key == "id":
                        current_select = self.states.get(device_id, {}).get("select", {})
                        current_scene = current_select.get("light_scene")

                        if current_scene:
                            # Check if the ID matches what we expect for this scene
                            light_scene_values = internal.get("light_scene_values", {})
                            expected_value = light_scene_values.get(current_scene)

                            # The expected value could be a dict {id, paramId} or just an int
                            expected_id = None
                            if isinstance(expected_value, dict):
                                expected_id = expected_value.get("id")
                            elif isinstance(expected_value, int):
                                expected_id = expected_value

                            if expected_id is not None:
                                if expected_id == data[key]:
                                    self.logger.debug(
                                        f"Scene ID {data[key]} confirms '{current_scene}' " f"scene is active on device '{self.get_device_name(device_id)}'"
                                    )
                                else:
                                    self.logger.warning(
                                        f"Scene ID mismatch on device '{self.get_device_name(device_id)}': "
                                        f"expected {expected_id} for '{current_scene}', got {data[key]}"
                                    )

                case _:
                    self.logger.warning(f"Govee update for device '{self.get_device_name(device_id)}' ({device_id}), unhandled state {key} => {data[key]}")

    # convert MQTT attributes to Govee capabilities
    def build_govee_capabilities(self: Govee2Mqtt, device_id: str, attribute: str, payload: Any) -> dict[str, dict]:
        component = self.devices[device_id]["component"]
        states = self.states[device_id]
        light = states.get("light", {})
        switch = states.get("switch", {})

        if isinstance(payload, int | str | float):
            payload = {attribute: payload}

        capabilities: dict[str, Any] = {}
        music_overrides: dict[str, Any] | None = None
        for key, value in payload.items():

            match key:
                case "state" | "light" | "value" | "power":
                    state_on = str(value).upper() == "ON"
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
                        self.logger.warning(f"ignored unknown or invalid attribute: {key} => {value}")

                case "color_temp":
                    # restrict color_temp to be >= min and <= max
                    if isinstance(value, str):
                        value = int(value)
                    color = min(max(value, component["cmps"]["light"]["min_kelvin"]), component["cmps"]["light"]["max_kelvin"])
                    light["color_temp"] = color
                    capabilities["colorTemperatureK"] = {
                        "type": "devices.capabilities.color_setting",
                        "instance": "colorTemperatureK",
                        "value": color,
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

                case "nightlight_scene":
                    internal = self.states.get(device_id, {}).get("internal", {})
                    scene_labels = internal.get("nightlight_scene_labels", {})
                    scene_value: int | None = None
                    if scene_labels:
                        scene_value = self.find_key_by_value(scene_labels, value)
                    if scene_value is None:
                        if isinstance(value, str) and value.isdigit():
                            scene_value = int(value)
                        elif isinstance(value, int):
                            scene_value = value
                    if scene_value is not None:
                        capabilities["nightlightScene"] = {
                            "type": "devices.capabilities.select_setting",
                            "instance": "nightlightScene",
                            "value": int(scene_value),
                        }
                case key if key.endswith("_scene"):
                    internal = self.states.get(device_id, {}).get("internal", {})

                    # First, try API-fetched light scenes (for light_scene specifically)
                    if key == "light_scene":
                        light_scene_values = internal.get("light_scene_values", {})
                        if light_scene_values:
                            selection = str(value)
                            scene_value_data = light_scene_values.get(selection)
                            if scene_value_data is not None:
                                # Update local state
                                self.upsert_state(device_id, select={"light_scene": selection})
                                # The value can be a dict {paramId, id} or a simple numeric value
                                capabilities["lightScene"] = {
                                    "type": "devices.capabilities.dynamic_scene",
                                    "instance": "lightScene",
                                    "value": scene_value_data,
                                }
                                continue

                    # Fall back to dynamic_scene_components (from device capabilities)
                    component_map = internal.get("dynamic_scene_components", {})
                    scene_instance = component_map.get(key)
                    if not scene_instance:
                        continue
                    scene_labels = internal.get("dynamic_scene_labels", {}).get(scene_instance, {})
                    selection = str(value)
                    scene_value = self.find_key_by_value(scene_labels, selection)
                    if scene_value is None and selection.isdigit():
                        scene_value = int(selection)
                    if scene_value is None:
                        continue
                    try:
                        numeric_value = int(scene_value)
                    except (TypeError, ValueError):
                        continue
                    capabilities[scene_instance] = {
                        "type": "devices.capabilities.dynamic_scene",
                        "instance": scene_instance,
                        "value": numeric_value,
                    }
                case "segment_index":
                    segments_state = self.states.get(device_id, {}).get("segments", {})
                    if not segments_state:
                        continue
                    segment_value = self._parse_segment_selection(value, segments_state.get("range"))
                    if segment_value is None:
                        continue
                    segment_label = self._segment_option_label(segment_value)
                    segments_state["selected_segment"] = segment_value
                    self.upsert_state(device_id, segments=segments_state, select={"segment_index": segment_label})
                case "segment_brightness":
                    segments_state = self.states.get(device_id, {}).get("segments", {})
                    if not segments_state:
                        continue
                    selected_segment = segments_state.get("selected_segment")
                    if selected_segment is None:
                        continue
                    brightness_range = segments_state.get("brightness_range") or {"min": 0, "max": 100}
                    brightness_value = self._coerce_int_in_range(value, brightness_range["min"], brightness_range["max"])
                    if brightness_value is None:
                        continue
                    segments_state["brightness"] = brightness_value
                    self.upsert_state(device_id, segments=segments_state, number={"segment_brightness": brightness_value})
                    capabilities["segmentedBrightness"] = {
                        "type": "devices.capabilities.segment_color_setting",
                        "instance": "segmentedBrightness",
                        "value": {
                            "segment": [int(selected_segment)],
                            "brightness": int(brightness_value),
                        },
                    }
                case "segment_rgb":
                    segments_state = self.states.get(device_id, {}).get("segments", {})
                    if not segments_state:
                        continue
                    selected_segment = segments_state.get("selected_segment")
                    if selected_segment is None:
                        continue
                    rgb_range = segments_state.get("color_range") or {"min": 0, "max": segments_state.get("rgb_max", 16777215)}
                    rgb_int = self._normalize_music_rgb(value, rgb_range.get("max"))
                    if rgb_int is None:
                        continue
                    if rgb_int < rgb_range.get("min", 0):
                        rgb_int = rgb_range.get("min", 0)
                    segments_state["rgb_value"] = rgb_int
                    self.upsert_state(device_id, segments=segments_state, number={"segment_rgb": rgb_int})
                    capabilities["segmentedColorRgb"] = {
                        "type": "devices.capabilities.segment_color_setting",
                        "instance": "segmentedColorRgb",
                        "value": {
                            "segment": [int(selected_segment)],
                            "rgb": int(rgb_int),
                        },
                    }

                case "work_mode":
                    internal = self.states.get(device_id, {}).get("internal", {})
                    work_mode_labels = internal.get("work_mode_value_labels", {})
                    if not work_mode_labels:
                        continue

                    manual_level_labels = internal.get("manual_level_labels", {})
                    gear_mode_labels = internal.get("gear_mode_labels", {})
                    selection = str(value)
                    selection_lower = selection.lower()
                    special_modes: list[tuple[str, dict[int | str, str]]] = []
                    if manual_level_labels:
                        special_modes.append(("manual", manual_level_labels))
                    if gear_mode_labels:
                        special_modes.append(("gearmode", gear_mode_labels))

                    def find_mode_key_by_name(name: str) -> int | None:
                        name_lower = name.lower()
                        for key, label in work_mode_labels.items():
                            if isinstance(label, str) and label.lower() == name_lower:
                                try:
                                    return int(key)
                                except (TypeError, ValueError):
                                    return None
                        return None

                    special_mode_names = {mode for mode, _ in special_modes}
                    work_mode_value = None
                    if selection_lower not in special_mode_names:
                        work_mode_value = self.find_key_by_value(work_mode_labels, selection)

                    payload_value: dict[str, int] = {}

                    if work_mode_value is not None:
                        payload_value["workMode"] = int(work_mode_value)
                    else:
                        matched = False
                        for mode_name, labels in special_modes:
                            if not labels:
                                continue
                            selection_value = self.find_key_by_value(labels, selection)
                            if selection_value is None:
                                continue
                            try:
                                selection_value_int = int(selection_value)
                            except (TypeError, ValueError):
                                continue
                            mode_key = find_mode_key_by_name(mode_name)
                            if mode_key is None:
                                continue
                            payload_value["workMode"] = int(mode_key)
                            payload_value["modeValue"] = selection_value_int
                            matched = True
                            break

                        if not matched:
                            fallback_value = self._normalize_mode_numeric_value(selection)
                            if fallback_value is not None:
                                for mode_name, labels in special_modes:
                                    if fallback_value in labels or str(fallback_value) in labels:
                                        mode_key = find_mode_key_by_name(mode_name)
                                        if mode_key is None:
                                            continue
                                        payload_value["workMode"] = int(mode_key)
                                        payload_value["modeValue"] = int(fallback_value)
                                        matched = True
                                        break

                    if payload_value:
                        capabilities["workMode"] = {
                            "type": "devices.capabilities.work_mode",
                            "instance": "workMode",
                            "value": payload_value,
                        }

                case "music_mode":
                    music_overrides = music_overrides or {}
                    music_overrides["mode"] = str(value)

                case "music_sensitivity":
                    music_overrides = music_overrides or {}
                    music_overrides["sensitivity"] = value

                case "music_auto_color":
                    music_overrides = music_overrides or {}
                    music_overrides["auto_color"] = value

                case "music_rgb":
                    music_overrides = music_overrides or {}
                    music_overrides["rgb"] = value

                case _:
                    self.logger.warning(f"ignored unknown or invalid attribute: {key} => {value}")

        # cannot send "turn" with either brightness or color
        if "brightness" in capabilities and "turn" in capabilities:
            del capabilities["turn"]
        if "color" in capabilities and "turn" in capabilities:
            del capabilities["turn"]

        if music_overrides:
            music_value = self._build_music_capability_value(device_id, music_overrides)
            if music_value:
                capabilities["musicMode"] = {
                    "type": "devices.capabilities.music_setting",
                    "instance": "musicMode",
                    "value": music_value,
                }

        return capabilities

    # send command to Govee -----------------------------------------------------------------------

    def _get_device_lock(self: Govee2Mqtt, device_id: str) -> asyncio.Lock:
        """Get or create a per-device lock to serialize commands to the same device."""
        if device_id not in self.command_locks:
            self.command_locks[device_id] = asyncio.Lock()
        return self.command_locks[device_id]

    def _get_pending_commands(self: Govee2Mqtt, device_id: str) -> dict[str, Any]:
        """Get or create a pending commands dict for a device."""
        if device_id not in self._pending_commands:
            self._pending_commands[device_id] = {}
        return self._pending_commands[device_id]

    def _normalize_color_key(self: Govee2Mqtt, key: str) -> str:
        """Normalize RGB color key aliases to 'rgb_color' for consistent conflict detection."""
        # build_govee_capabilities treats "rgb_color", "rgb", and "color" as equivalent
        if key in ("rgb", "color"):
            return "rgb_color"
        return key

    async def send_command(self: Govee2Mqtt, device_id: str, attribute: str, command: Any) -> None:
        """Batch commands for the same device to handle conflicting color modes.

        Home Assistant sends rgb_color and color_temp as separate MQTT messages,
        but they are mutually exclusive. We collect commands within a short window
        and keep only the color mode that arrived last.
        """
        if device_id == "service":
            self.logger.error(f'why are you trying to send {command} to the "service"? Ignoring you.')
            return

        # Normalize the attribute name for batching
        normalized_attr = self._normalize_color_key(attribute.lower())

        # Get the per-device lock
        lock = self._get_device_lock(device_id)

        # Phase 1: Add command to pending (briefly hold lock)
        async with lock:
            pending = self._get_pending_commands(device_id)

            # Track arrival order for color mode commands
            order_key = "_order"
            if order_key not in pending:
                pending[order_key] = []

            # Check if we're the first command in this batch
            is_first = len(pending) <= 1  # Only _order key present

            # Store the command
            if isinstance(command, dict):
                for key, value in command.items():
                    # Normalize RGB key aliases for consistent conflict detection
                    normalized_key = self._normalize_color_key(key)
                    pending[normalized_key] = value
                    # Track arrival order for color modes
                    if normalized_key in ("rgb_color", "color_temp"):
                        pending[order_key] = [a for a in pending[order_key] if a != normalized_key]
                        pending[order_key].append(normalized_key)
            else:
                pending[normalized_attr] = command
                # Track arrival order for color modes
                if normalized_attr in ("rgb_color", "color_temp"):
                    pending[order_key] = [a for a in pending[order_key] if a != normalized_attr]
                    pending[order_key].append(normalized_attr)

        # Only the first caller waits and processes the batch
        if not is_first:
            return

        # Wrap entire batch processing in try/finally to ensure pending is cleared
        # even if cancelled during sleep or any other failure
        batched_command: dict[str, Any] = {}
        try:
            # Phase 2: Wait for more commands to arrive (lock NOT held)
            await asyncio.sleep(COLOR_MODE_BATCH_WINDOW)

            # Phase 3: Process and send the batched commands (hold lock)
            async with lock:
                pending = self._get_pending_commands(device_id)

                # Check if there are still pending commands
                order_key = "_order"
                if not pending or pending == {order_key: []}:
                    pending.clear()
                    return

                # Extract arrival order and remove the tracking key
                arrival_order = pending.pop(order_key, [])

                # If both rgb_color and color_temp are present, keep only the LAST one
                has_rgb = "rgb_color" in pending
                has_color_temp = "color_temp" in pending
                if has_rgb and has_color_temp:
                    # Determine which arrived last
                    last_color_mode = arrival_order[-1] if arrival_order else "color_temp"
                    if last_color_mode == "color_temp":
                        # Extract brightness from rgb_color before dropping it.
                        # HA embeds brightness in the RGB values (e.g., dim orange [76,30,0] vs bright [255,127,0]).
                        # The max channel value represents the brightness level (0-255).
                        if "brightness" not in pending:
                            rgb = pending.get("rgb_color")
                            rgb_values: list[int] | None = None
                            # Handle both list/tuple and string formats (e.g., "255,128,0")
                            if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
                                try:
                                    rgb_values = [int(rgb[0]), int(rgb[1]), int(rgb[2])]
                                except (TypeError, ValueError):
                                    rgb_values = None
                            elif isinstance(rgb, str) and "," in rgb:
                                try:
                                    parts = rgb.split(",", 3)
                                    rgb_values = [int(parts[0]), int(parts[1]), int(parts[2])]
                                except (TypeError, ValueError, IndexError):
                                    rgb_values = None
                            if rgb_values:
                                try:
                                    inferred_brightness = max(rgb_values)
                                    if inferred_brightness > 0:
                                        # Scale from 0-255 to 0-100 for Govee API
                                        pending["brightness"] = round(inferred_brightness * 100 / 255)
                                        self.logger.debug(f"inferred brightness={pending['brightness']} from rgb_color {rgb} for {device_id}")
                                except (TypeError, ValueError) as e:
                                    self.logger.warning(f"failed to infer brightness from rgb_color {rgb}: {e}")
                        pending.pop("rgb_color", None)
                        self.logger.debug(f"dropping rgb_color in favor of color_temp (arrived last) for {device_id}")
                    else:
                        pending.pop("color_temp", None)
                        self.logger.debug(f"dropping color_temp in favor of rgb_color (arrived last) for {device_id}")

                # Take ownership of pending commands and clear
                batched_command = dict(pending)
                pending.clear()

                # Phase 4: Send the batched command (lock held to maintain ordering)
                # This ensures commands complete in the order they were batched,
                # preventing race conditions where a slow API call completes after a fast one.
                if batched_command:
                    await self._send_single_command(device_id, attribute, batched_command)
        except asyncio.CancelledError:
            # If cancelled, still clear pending to prevent stuck commands
            async with lock:
                self._get_pending_commands(device_id).clear()
            raise
        except Exception:
            # On any other error, clear pending and re-raise
            async with lock:
                self._get_pending_commands(device_id).clear()
            raise

    async def _send_single_command(self: Govee2Mqtt, device_id: str, attribute: str, command: Any) -> None:
        """Send a single (possibly batched) command to the Govee API."""
        # convert what we received in the command to Govee API capabilities
        capabilities = self.build_govee_capabilities(device_id, attribute, command)
        if not capabilities:
            self.logger.debug(f"nothing to send Govee for '{self.get_device_name(device_id)}' for command {command}")
            return

        need_boost = False
        for key in capabilities:
            self.logger.debug(f"posting {key} to Govee API: " + ", ".join(f"{k}={v}" for k, v in capabilities[key].items()))
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
                self.logger.debug(f"got response from Govee API: {response}")
                await self.publish_device_state(device_id)

                # remove from boosted list (if there), since we got a change
                if device_id in self.boosted:
                    self.boosted.remove(device_id)
            else:
                self.logger.debug(f"no details in response from Govee API: {response}")
                need_boost = True

        # if we send a command and did not get a state change back on the response
        # lets boost this device to refresh it soon, just in case
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
                self.logger.error(f"unrecognized message to {self.mqtt_helper.service_slug}: {handler} with {message}")
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
            self.logger.info("state saved after signal")
        except Exception as e:
            self.logger.warning(f"failed to save state on signal: {e}")

        def _force_exit() -> None:
            self.logger.warning("force-exiting process after signal")
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

    def _normalize_mode_numeric_value(self: Govee2Mqtt, value: Any) -> int | None:
        if isinstance(value, dict):
            for key in ("value", "level", "code"):
                if key in value and value[key] is not None:
                    value = value[key]
                    break
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
            digits = "".join(ch for ch in stripped if ch.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    return None
        return None

    def _normalize_music_auto_color_state(self: Govee2Mqtt, value: Any, mapping: Mapping[str, int]) -> bool | None:
        if value is None:
            return None
        normalized_value = value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"on", "off", "true", "false"}:
                return lowered in {"on", "true"}
            if lowered in mapping:
                return lowered == "on"
            if lowered.startswith("0x") or lowered.startswith("#"):
                return None
            if lowered.isdigit():
                normalized_value = int(lowered)
            else:
                return None
        if isinstance(normalized_value, bool):
            return normalized_value
        if isinstance(normalized_value, (int, float)):
            normalized_int = int(normalized_value)
            for name, mapped_value in mapping.items():
                if mapped_value == normalized_int:
                    return name.lower() == "on"
            return normalized_int > 0
        return None

    def _normalize_music_rgb(self: Govee2Mqtt, value: Any, rgb_max: int | None = None) -> int | None:
        if value is None:
            return None
        rgb_int: int | None = None
        if isinstance(value, (int, float)):
            rgb_int = int(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.startswith("#"):
                try:
                    rgb_int = int(stripped[1:], 16)
                except ValueError:
                    return None
            elif stripped.lower().startswith("0x"):
                try:
                    rgb_int = int(stripped, 16)
                except ValueError:
                    return None
            elif "," in stripped:
                parts = stripped.split(",", 3)
                try:
                    rgb_values = [int(part.strip()) for part in parts[:3]]
                except ValueError:
                    return None
                if len(rgb_values) == 3:
                    try:
                        rgb_int = self.rgb_to_number(rgb_values)
                    except ValueError:
                        return None
            elif stripped.isdigit():
                rgb_int = int(stripped)
        elif isinstance(value, (list, tuple)):
            if len(value) == 3:
                try:
                    rgb_values = [int(value[0]), int(value[1]), int(value[2])]
                except (TypeError, ValueError):
                    rgb_values = None
                if rgb_values is not None:
                    try:
                        rgb_int = self.rgb_to_number(rgb_values)
                    except ValueError:
                        rgb_int = None
        elif isinstance(value, dict):
            try:

                def _channel(primary: str, alternate: str) -> int:
                    raw = value.get(primary)
                    if raw is None:
                        raw = value.get(alternate)
                    if raw is None:
                        raw = 0
                    try:
                        return int(raw)
                    except (TypeError, ValueError):
                        return 0

                rgb_values = [
                    _channel("r", "red"),
                    _channel("g", "green"),
                    _channel("b", "blue"),
                ]
                rgb_int = self.rgb_to_number(rgb_values)
            except (TypeError, ValueError):
                rgb_int = None

        if rgb_int is None:
            return None
        if rgb_int < 0:
            rgb_int = 0
        if rgb_max is not None:
            rgb_int = min(rgb_int, rgb_max)
        return rgb_int

    def _coerce_int_in_range(self: Govee2Mqtt, value: Any, minimum: int, maximum: int) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return max(min(parsed, int(maximum)), int(minimum))

    def _segment_option_label(self: Govee2Mqtt, segment_id: int) -> str:
        return f"Segment {segment_id}"

    def _parse_segment_selection(self: Govee2Mqtt, selection: Any, segment_range: Mapping[str, int] | None = None) -> int | None:
        if isinstance(selection, (int, float)):
            segment = int(selection)
        elif isinstance(selection, str):
            digits = "".join(ch for ch in selection if ch.isdigit())
            if not digits:
                return None
            segment = int(digits)
        else:
            return None
        if segment_range:
            minimum = int(segment_range.get("min", segment))
            maximum = int(segment_range.get("max", segment))
            if segment < minimum or segment > maximum:
                segment = max(min(segment, maximum), minimum)
        return segment

    def _scene_component_key(self: Govee2Mqtt, instance: str) -> str:
        key = re.sub(r"(?<!^)(?=[A-Z])", "_", instance).lower()
        if not key.endswith("_scene"):
            key = f"{key}_scene"
        return key

    def _scene_instance_from_key(self: Govee2Mqtt, key: str) -> str:
        base = key[:-6] if key.endswith("_scene") else key
        parts = base.split("_")
        if not parts:
            return base
        instance = parts[0]
        if len(parts) > 1:
            instance += "".join(word.capitalize() for word in parts[1:])
        return instance

    def _build_music_capability_value(self: Govee2Mqtt, device_id: str, overrides: Mapping[str, Any]) -> dict[str, int] | None:
        music_state = self.states.get(device_id, {}).get("music", {})
        if not music_state:
            return None
        options = music_state.get("options", {})
        if not options:
            return None

        mode_name = overrides.get("mode") or music_state.get("mode")
        if not mode_name:
            return None
        if not isinstance(mode_name, str):
            mode_name = str(mode_name)

        mode_value = options.get(mode_name)
        if mode_value is None:
            mode_value = self.find_key_by_value(options, mode_name)
        if mode_value is None:
            return None

        payload: dict[str, int] = {"musicMode": int(mode_value)}

        sensitivity = overrides.get("sensitivity", music_state.get("sensitivity"))
        if isinstance(sensitivity, str):
            if sensitivity.isdigit():
                sensitivity = int(sensitivity)
            else:
                sensitivity = music_state.get("sensitivity")
        if isinstance(sensitivity, (int, float)):
            payload["sensitivity"] = int(sensitivity)
        else:
            payload["sensitivity"] = int(music_state.get("sensitivity", 100))

        auto_color_override = overrides.get("auto_color")
        auto_color_state = (
            self._normalize_music_auto_color_state(auto_color_override, music_state.get("auto_color_values", {}))
            if auto_color_override is not None
            else music_state.get("auto_color_state")
        )
        auto_color_values = music_state.get("auto_color_values", {})
        if auto_color_state is not None and auto_color_values:
            key = "on" if auto_color_state else "off"
            auto_color_value = auto_color_values.get(key)
            if auto_color_value is not None:
                payload["autoColor"] = int(auto_color_value)

        rgb_override = overrides.get("rgb")
        rgb_int = self._normalize_music_rgb(rgb_override, music_state.get("rgb_max")) if rgb_override is not None else music_state.get("rgb_value")
        if rgb_int is not None:
            payload["rgb"] = int(rgb_int)

        return payload

    def find_key_by_value(self: Govee2Mqtt, d: Mapping[Any, Any], target: Any) -> Any:
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

    # Device properties ---------------------------------------------------------------------------

    def get_device_name(self: Govee2Mqtt, device_id: str) -> str:
        return cast(str, self.devices[device_id]["component"]["device"]["name"])

    def get_raw_id(self: Govee2Mqtt, device_id: str) -> str:
        return cast(str, self.states[device_id]["internal"]["raw_id"])

    def get_device_sku(self: Govee2Mqtt, device_id: str) -> str:
        return cast(str, self.states[device_id]["internal"]["sku"])

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
