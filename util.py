# This software is licensed under the MIT License, which allows you to use,
# copy, modify, merge, publish, distribute, and sell copies of the software,
# with the requirement to include the original copyright notice and this
# permission notice in all copies or substantial portions of the software.
#
# The software is provided 'as is', without any warranty.

import os
import yaml
import logging


# Helper functions
def read_file(file_name, strip_newlines=True, default=None, encoding="utf-8"):
    """Read a file and return its contents.
    Optionally strip newlines and return a default value if the file is missing.
    """
    try:
        with open(file_name, "r", encoding=encoding) as f:
            data = f.read()
            return data.replace("\n", "") if strip_newlines else data
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def read_version():
    """Read VERSION file next to this script, or return 'unknown'."""
    # Find the directory this file lives in (not the current working dir)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    version_path = os.path.join(base_dir, "VERSION")

    # Try to read from the file, otherwise check env var, otherwise fallback
    try:
        with open(version_path, "r") as f:
            return f.read().strip() or "unknown"
    except FileNotFoundError:
        env_version = os.getenv("APP_VERSION")
        return env_version.strip() if env_version else "unknown"


def number_to_rgb(number, max_value):
    """Map a number in [0, max_value] to a red→green gradient with optional blue hue."""
    if max_value <= 0:
        raise ValueError("max_value must be > 0")

    normalized = min(max(number / max_value, 0.0), 1.0)  # clamp to [0,1]
    r = int((1 - normalized) * 255)
    g = int(normalized * 255)
    b = int(((0.5 - abs(normalized - 0.5)) * 2 * 255)) if normalized > 0.5 else 0
    return {"r": r, "g": g, "b": b}


def rgb_to_number(rgb):
    """Pack an RGB dict into an integer (0xRRGGBB)."""
    try:
        r = int(rgb.get("r", 0)) & 0xFF
        g = int(rgb.get("g", 0)) & 0xFF
        b = int(rgb.get("b", 0)) & 0xFF
        return (r << 16) | (g << 8) | b
    except Exception as e:
        raise ValueError(f"Invalid RGB dict: {rgb!r}") from e


def find_key_by_value(d, target):
    return next((k for k, v in d.items() if v == target), None)


def load_config(config_arg=None):
    """Load configuration from YAML file or environment variables.

    Args:
        config_arg (str): Either a full path to config.yaml, a directory containing it,
                          or None (defaults to /config/config.yaml).
    Returns:
        dict: Merged configuration dictionary with defaults.
    """
    version = read_version()
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
        "homeassistant": mqtt.get("homeassistant")
        or (os.getenv("MQTT_HOMEASSISTANT", "false").lower() == "true"),
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
            govee.get("device_list_interval") or os.getenv("GOVEE_LIST_INTERVAL", 3600)
        ),
    }

    config = {
        "mqtt": mqtt,
        "govee": govee,
        "debug": config.get("debug", os.getenv("DEBUG", "").lower() == "true"),
        "hide_ts": config.get("hide_ts", os.getenv("HIDE_TS", "").lower() == "true"),
        "timezone": config.get("timezone", os.getenv("TZ", "UTC")),
        "config_from": config_from,
        "config_path": config_path,
        "version": version,
    }

    # Validate required fields
    if not config["govee"].get("api_key"):
        raise ValueError(
            "`govee.api_key` required in config file or GOVEE_API_KEY env var"
        )

    return config
