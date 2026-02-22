# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from typing import Any

import pytest


@pytest.fixture
def sample_govee_config() -> dict[str, Any]:
    """Return a minimal valid config dict for govee2mqtt."""
    return {
        "mqtt": {
            "host": "localhost",
            "port": 1883,
            "qos": 0,
            "protocol_version": "5",
            "username": "testuser",
            "password": "testpass",
            "tls_enabled": False,
            "prefix": "govee2mqtt",
            "discovery_prefix": "homeassistant",
        },
        "govee": {
            "api_key": "test-api-key-12345",
            "device_interval": 30,
            "device_boost_interval": 5,
            "device_list_interval": 3600,
        },
        "debug": False,
        "timezone": "UTC",
        "config_from": "test",
        "config_path": "/tmp",
        "version": "0.0.0-test",
    }
