# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import argparse
import json
import logging
from pathlib import Path


class Base:
    def __init__(self, *, args: argparse.Namespace | None = None, **kwargs):
        super().__init__(**kwargs)

        self.args = args

        # load config first
        cfg_arg = getattr(args, "config", None)
        self.config = self.load_config(cfg_arg)

        self.mqtt_config = self.config["mqtt"]
        self.govee_config = self.config["govee"]

        # now we can setup logging
        time_fmt = "%(asctime)s.%(msecs)03d "
        dbg_base_fmt = (
            "[%(levelname)s] %(name)s (%(funcName)s#%(lineno)d):  %(message)s"
        )
        std_base_fmt = "[%(levelname)s] %(name)s: %(message)s"
        fmt = dbg_base_fmt if self.config.get("debug") else std_base_fmt
        if not self.config.get("hide_ts"):
            fmt = time_fmt + fmt

        level = logging.DEBUG if self.config.get("debug") else logging.INFO

        # lets start (better) logging, and ignoring others
        logging.basicConfig(
            level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S", force=True
        )

        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
        self.logger = logging.getLogger("govee2mqtt")
        self.logger.info(
            f"config loaded from {self.config['config_from']} ({self.config['config_path']})"
        )

        self.devices = {}
        self.states = {}
        self.boosted = []

        self.running = False
        self.discovery_complete = False

        self.mqttc = None
        self.mqtt_connect_time = None
        self.mqtt_client_id = self._build_client_id(self.config["mqtt"]["prefix"])

        self.service = self.mqtt_config["prefix"]
        self.service_name = f"{self.service} service"
        self.service_slug = self.service

        self.device_interval = self.config["govee"].get("device_interval", 30)
        self.device_boost_interval = self.config["govee"].get(
            "device_boost_interval", 5
        )
        self.device_list_interval = self.config["govee"].get(
            "device_list_interval", 300
        )

        self.api_key = self.config["govee"]["api_key"]
        self.rate_limited = False
        self.api_calls = 0
        self.last_call_date = None
        self.timezone = self.config["timezone"]

    def __enter__(self):
        super_enter = getattr(super(), "__enter__", None)
        if callable(super_enter):
            super_enter()

        self.mqttc_create()
        self.restore_state()
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        super_exit = getattr(super(), "__exit__", None)
        if callable(super_exit):
            super_exit(exc_type, exc_val, exc_tb)

        """Gracefully stop the service when leaving a context (e.g., Docker shutdown)."""
        self.running = False
        self.save_state()

        if self.mqttc is not None:
            try:
                self.publish_service_availability("offline")
                # Stop the Paho background network thread
                self.mqttc.loop_stop()
            except Exception as e:
                self.logger.debug(f"MQTT loop_stop failed: {e}")

            if self.mqttc.is_connected():
                try:
                    self.mqttc.disconnect()
                    self.logger.info("Disconnected from MQTT broker")
                except Exception as e:
                    self.logger.warning(f"Error during MQTT disconnect: {e}")

        self.logger.info("Exiting gracefully")

    def save_state(self):
        data_file = Path(self.config["config_path"]) / "govee2mqtt.dat"
        state = {
            "api_calls": self.api_calls,
            "last_call_date": self.last_call_date,
        }
        with open(data_file, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)
        self.logger.info(f"Saved state to {data_file}")

    def restore_state(self):
        data_file = Path(self.config["config_path"]) / "govee2mqtt.dat"
        with open(data_file, "r") as file:
            state = json.loads(file.read())
            self.restore_state_values(state["api_calls"], state["last_call_date"])
        self.logger.info(f"Restored state from {data_file}")
