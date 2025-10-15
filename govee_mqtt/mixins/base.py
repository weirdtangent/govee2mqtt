from .._imports import *

import govee_api
import json
import logging
from pathlib import Path

class BaseMixin:
    def __init__(self, config):
        self.running = False
        self.discovery_complete = False

        self.config = config
        self.mqtt_config = config['mqtt']
        self.govee_config = config['govee']

        self.devices = {} # for storing the device data we send via MQTT
        self.states = {} # for storing device config that we need to remember: options, scenes, enums, etc
        self.boosted = []

        self.logger = logging.getLogger(__name__)

        self.mqttc = None
        self.mqtt_connect_time = None
        self.client_id = self.get_new_client_id()
        self.service = self.mqtt_config["prefix"]
        self.service_name = f"{self.service} service"
        self.service_slug = self.service
        self.qos = self.mqtt_config['qos']

        self.device_interval = config['govee'].get('device_interval', 30)
        self.device_boost_interval = config['govee'].get('device_boost_interval', 5)
        self.device_list_interval = config['govee'].get('device_list_interval', 300)

    def __enter__(self):
        self.mqttc_create()
        self.goveec = govee_api.GoveeAPI(self.config)
        self.restore_state()
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Gracefully stop the service when leaving a context (e.g., Docker shutdown)."""
        self.running = False
        self.save_state()

        if self.mqttc is not None:
            try:
                self.publish_service_availability('offline')
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
            'api_calls': self.goveec.api_calls,
            'last_call_date': self.goveec.last_call_date,
        }
        with open(data_file, 'w', encoding='utf-8') as file:
            json.dump(state, file, indent=4)
        self.logger.info(f'Saved state to {data_file}')

    def restore_state(self):
        data_file = Path(self.config["config_path"]) / "govee2mqtt.dat"
        with open(data_file, 'r') as file:
            state = json.loads(file.read())
            self.goveec.restore_state_values(state['api_calls'], state['last_call_date'])
        self.logger.info(f'Restored state from {data_file}')

