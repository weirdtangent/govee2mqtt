# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import argparse
import asyncio
from asyncio import AbstractEventLoop
from datetime import datetime, date
import json
from json_logging import get_logger
import logging
from mqtt_helper import MqttHelper
import os
from paho.mqtt.client import Client
from pathlib import Path
from types import TracebackType

from typing import Any, Self, cast

from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class Base:
    def __init__(self: Govee2Mqtt, args: argparse.Namespace | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.args = args
        self.logger = get_logger(__name__)

        # now load self.config right away
        cfg_arg = getattr(args, "config", None)
        self.config = self.load_config(cfg_arg)

        if not self.config["mqtt"] or not self.config["blink"]:
            raise ValueError("config was not loaded")

        # down in trenches if we have to
        if self.config.get("debug"):
            self.logger.setLevel(logging.DEBUG)

        self.mqtt_config = self.config["mqtt"]

        self.service = self.mqtt_config["prefix"]
        self.service_name = f"{self.service} service"

        self.mqtt_helper = MqttHelper(self.service)

        self.running = False
        self.discovery_complete = False
        self.loop: AbstractEventLoop

        self.devices: dict[str, Any] = {}
        self.states: dict[str, Any] = {}
        self.boosted: list[str] = []
        self.events: list[str] = []

        self.running = False
        self.discovery_complete = False

        self.mqttc: Client
        self.mqtt_connect_time: datetime
        self.client_id = self.mqtt_helper.client_id()

        self.qos = self.mqtt_config["qos"]

        self.session: Any = None
        self.service = self.mqtt_config["prefix"]
        self.service_name = f"{self.service} service"

        self.device_interval = self.config["govee"].get("device_interval", 30)
        self.device_boost_interval = self.config["govee"].get("device_boost_interval", 5)
        self.device_list_interval = self.config["govee"].get("device_list_interval", 300)

        self.api_key = self.config["govee"]["api_key"]
        self.rate_limited = False
        self.api_calls = 0
        self.last_call_date: date
        self.timezone = self.config["timezone"]

    def __enter__(self: Self) -> Govee2Mqtt:
        super_enter = getattr(super(), "__enter__", None)
        if callable(super_enter):
            super_enter()

        cast(Any, self).mqttc_create()
        cast(Any, self).restore_state()
        self.running = True

        return cast(Govee2Mqtt, self)

    def __exit__(self: Self, exc_type: BaseException | None, exc_val: BaseException | None, exc_tb: TracebackType) -> None:
        super_exit = getattr(super(), "__exit__", None)
        if callable(super_exit):
            super_exit(exc_type, exc_val, exc_tb)

        self.running = False
        cast(Any, self).save_state()

        if cast(Any, self).session and not cast(Any, self).session.closed:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                loop.create_task(cast(Any, self).session.close())
            else:
                asyncio.run(cast(Any, self).session.close())

        if cast(Any, self).mqttc is not None:
            try:
                cast(Any, self).publish_service_availability("offline")
                cast(Any, self).mqttc.loop_stop()
            except Exception as e:
                self.logger.debug(f"MQTT loop_stop failed: {e}")

            if cast(Any, self).mqttc.is_connected():
                try:
                    cast(Any, self).mqttc.disconnect()
                    self.logger.info("Disconnected from MQTT broker")
                except Exception as e:
                    self.logger.warning(f"Error during MQTT disconnect: {e}")

        self.logger.info("Exiting gracefully")

    def save_state(self: Govee2Mqtt) -> None:
        data_file = Path(self.config["config_path"]) / "govee2mqtt.dat"
        state = {
            "api_calls": self.api_calls,
            "last_call_date": str(self.last_call_date),
        }
        with open(data_file, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)
        self.logger.info(f"Saved state to {data_file}")

    def restore_state(self: Govee2Mqtt) -> None:
        data_file = Path(self.config["config_path"]) / "govee2mqtt.dat"
        if os.path.exists(data_file):
            with open(data_file, "r") as file:
                state = json.loads(file.read())
                self.restore_state_values(state["api_calls"], state["last_call_date"])
            self.logger.info(f"Restored state from {data_file}")
