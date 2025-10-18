# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import colorsys
import os
from typing import Any
import yaml
import pathlib
import logging
from importlib.metadata import version as pkg_version

READY_FILE = os.getenv("READY_FILE", "/tmp/govee2mqtt.ready")

# Helper functions --------------------------------------------------------------------------------


class UtilMixin:
    def mark_ready(self):
        pathlib.Path(READY_FILE).touch()

    def heartbeat_ready(self):
        pathlib.Path(READY_FILE).touch()

    def number_to_rgb_linear(self, number, max_value):
        if max_value is None or max_value <= 0:
            raise ValueError("max_value must be > 0")
        t = max(0.0, min(1.0, number / max_value))
        r = int(255 * (1.0 - t))  # or round(...) if you prefer 128 at 50%
        g = int(255 * t)
        b = 0
        return {"r": r, "g": g, "b": b}

    def number_to_rgb_hsv(self, number, max_value, value=1.0, saturation=1.0):
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

    def number_to_rgb_bluepop(self, number, max_value, brightness=255):
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

    def rgb_to_number(self, rgb):
        """Pack an RGB dict into an integer (0xRRGGBB)."""
        try:
            if isinstance(rgb, (list, tuple)):
                r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            elif isinstance(rgb, dict):
                r = int(rgb.get("r", 0))
                g = int(rgb.get("g", 0))
                b = int(rgb.get("b", 0))
            else:
                raise TypeError(f"Unsupported RGB type: {type(rgb).__name__}")
            return (r << 16) | (g << 8) | b
        except Exception as e:
            raise ValueError(f"Invalid RGB value: {rgb!r}") from e

    def find_key_by_value(self, d: dict[str, Any], target):
        return next((k for k, v in d.items() if v == target), None)

    def load_config(self, config_arg=None):
        """Load configuration from YAML file or environment variables.

        Args:
            config_arg (str): Either a full path to config.yaml, a directory containing it,
                              or None (defaults to /config/config.yaml).
        Returns:
            dict: Merged configuration dictionary with defaults.
        """
        version = pkg_version("govee2mqtt")
        config_from = "env"
        config = {}

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
            logging.warning(
                f"Config file not found at {config_file}, falling back to environment vars"
            )

        # Merge with environment vars (env vars override nothing if file exists)
        mqtt = config.get("mqtt", {})
        govee = config.get("govee", {})

        mqtt = {
            "host": mqtt.get("host") or os.getenv("MQTT_HOST", "localhost"),
            "port": int(mqtt.get("port") or os.getenv("MQTT_PORT", 1883)),
            "qos": int(mqtt.get("qos") or os.getenv("MQTT_QOS", 0)),
            "username": mqtt.get("username") or os.getenv("MQTT_USERNAME", ""),
            "password": mqtt.get("password") or os.getenv("MQTT_PASSWORD", ""),
            "tls_enabled": mqtt.get("tls_enabled")
            or (os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"),
            "tls_ca_cert": mqtt.get("tls_ca_cert") or os.getenv("MQTT_TLS_CA_CERT"),
            "tls_cert": mqtt.get("tls_cert") or os.getenv("MQTT_TLS_CERT"),
            "tls_key": mqtt.get("tls_key") or os.getenv("MQTT_TLS_KEY"),
            "prefix": mqtt.get("prefix") or os.getenv("MQTT_PREFIX", "govee2mqtt"),
            "discovery_prefix": mqtt.get("discovery_prefix")
            or os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        }

        govee = {
            "api_key": govee.get("api_key") or os.getenv("GOVEE_API_KEY"),
            "device_interval": int(
                govee.get("device_interval") or os.getenv("GOVEE_DEVICE_INTERVAL", 30)
            ),
            "device_boost_interval": int(
                govee.get("device_boost_interval")
                or os.getenv("GOVEE_DEVICE_BOOST_INTERVAL", 5)
            ),
            "device_list_interval": int(
                govee.get("device_list_interval")
                or os.getenv("GOVEE_LIST_INTERVAL", 3600)
            ),
        }

        config = {
            "mqtt": mqtt,
            "govee": govee,
            "debug": config.get("debug", os.getenv("DEBUG", "").lower() == "true"),
            "hide_ts": config.get(
                "hide_ts", os.getenv("HIDE_TS", "").lower() == "true"
            ),
            "timezone": config.get("timezone", os.getenv("TZ", "UTC")),
            "config_from": config_from,
            "config_path": config_path,
            "version": version,
        }

        # Validate required fields
        if not config["govee"].get("api_key"):
            raise TypeError(
                "`govee.api_key` required in config file or GOVEE_API_KEY env var"
            )

        return config
