# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import json
import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import random
import ssl
import string
import time


class MqttMixin:
    def _build_client_id(self, prefix):
        return (
            prefix
            + "-"
            + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        )

    def mqttc_create(self):
        if not hasattr(self, "config"):
            raise RuntimeError("config not initialized; ensure Base.__init__ ran")

        client_id = self._build_client_id(self.config["mqtt"]["prefix"])

        self.mqttc = mqtt.Client(
            client_id=client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            reconnect_on_failure=False,
            protocol=mqtt.MQTTv5,
        )

        if self.mqtt_config.get("tls_enabled"):
            self.mqttc.tls_set(
                ca_certs=self.mqtt_config.get("tls_ca_cert"),
                certfile=self.mqtt_config.get("tls_cert"),
                keyfile=self.mqtt_config.get("tls_key"),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            )
        if self.mqtt_config.get("username") or self.mqtt_config.get("password"):
            self.mqttc.username_pw_set(
                username=self.mqtt_config.get("username") or None,
                password=self.mqtt_config.get("password") or None,
            )

        self.mqttc.on_connect = self.mqtt_on_connect
        self.mqttc.on_disconnect = self.mqtt_on_disconnect
        self.mqttc.on_message = self.mqtt_on_message
        self.mqttc.on_subscribe = self.mqtt_on_subscribe
        self.mqttc.on_log = self.mqtt_on_log

        # Define a "last will" message (LWT):
        self.mqttc.will_set(
            self.get_service_topic("status"), "offline", qos=1, retain=True
        )

        try:
            host = self.mqtt_config.get("host")
            port = self.mqtt_config.get("port")
            self.logger.info(
                f"Connecting to MQTT broker at {host}:{port} as {self.mqtt_client_id}"
            )

            props = Properties(PacketTypes.CONNECT)
            props.SessionExpiryInterval = 0

            self.mqttc.connect(host=host, port=port, keepalive=60, properties=props)
            self.logger.info(f"Successful connection to {host} MQTT broker")

            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            self.logger.error(f"Failed to connect to MQTT host {host}: {error}")
            self.running = False
        except Exception as error:
            self.logger.error(
                f"Network problem trying to connect to MQTT host {host}: {error}"
            )
            self.running = False

    def mqtt_on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.value != 0:
            self.logger.error(f"MQTT failed to connect ({reason_code.getName()})")
            self.running = False
            return

        self.publish_service_discovery()
        self.publish_service_availability()
        self.publish_service_state()

        self.logger.info("Subscribing to topics on MQTT")
        client.subscribe("homeassistant/status")
        client.subscribe(f"{self.service_slug}/service/+/set")
        client.subscribe(f"{self.service_slug}/service/+/command")
        client.subscribe(f"{self.service_slug}/light/#")
        client.subscribe(f"{self.service_slug}/switch/#")

    def mqtt_on_disconnect(self, client, userdata, flags, reason_code, properties):
        if reason_code.value != 0:
            self.logger.error(f"MQTT lost connection ({reason_code.getName()})")
        else:
            self.logger.info("Closed MQTT connection")

        if self.running and (
            self.mqtt_connect_time is None or time.time() > self.mqtt_connect_time + 10
        ):
            # lets use a new client_id for a reconnect attempt
            self.mqtt_client_id = self.build_client_id(self.mqtt_config["prefix"])
            self.mqttc_create()
        else:
            self.logger.info("MQTT disconnect — stopping service loop")
            self.running = False

    def mqtt_on_log(self, client, userdata, paho_log_level, msg):
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
            self.logger.error(f"MQTT logged: {msg}")
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_WARNING:
            self.logger.warning(f"MQTT logged: {msg}")

    def mqtt_on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = self._decode_payload(msg.payload)
        components = topic.split("/")

        self.logger.info(f"Got message on topic: {topic} with {payload}")

        # Dispatch based on type of message
        if components[0] == self.mqtt_config["discovery_prefix"]:
            self.logger.debug("  Looks like a HomeAssistant message")
            return self._handle_homeassistant_message(payload)

        if components[0] == self.service_slug:
            if components[1] == "service":
                self.logger.debug("  Looks like a govee2mqtt-service message")
                return self.handle_service_message(components[2], payload)
            self.logger.debug("  Looks like a govee device command")
            return self._handle_device_topic(components, payload)

        self.logger.debug(
            f"Did not process message on MQTT topic: {topic} with {payload}"
        )

    def _decode_payload(self, raw):
        """Try to decode MQTT payload as JSON, fallback to UTF-8 string, else None."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            # Fallback: try to decode as UTF-8 string
            try:
                return raw.decode("utf-8")
            except Exception:
                self.logger.warning("Failed to decode MQTT payload")
                return None

    def _handle_homeassistant_message(self, payload):
        if payload == "online":
            self.rediscover_all()
            self.logger.info("Home Assistant came online — rediscovering devices")

    def _handle_device_topic(self, components, payload):
        vendor, device_id, attribute = self._parse_device_topic(components)
        if not vendor or not vendor.startswith(self.service_slug):
            self.logger.debug(
                f"Ignoring non-Govee device topic for {vendor}: {'/'.join(components)}"
            )
            return
        if not self.devices.get(device_id, None):
            self.logger.warning(f"Got MQTT message for unknown device: {device_id}")
            return

        if attribute and isinstance(payload, str):
            payload = {attribute: payload}

        self.logger.debug(
            f"Got message for {self.get_device_name(device_id)}: {payload}"
        )
        self.send_command(device_id, payload)

    def _parse_device_topic(self, components):
        """Extract (vendor, device_id, attribute) from an MQTT topic components list (underscore-delimited)."""
        try:
            # Example topics:
            # govee2mqtt/light/govee2mqtt_2BEFD0C907BB6BF2/set
            # govee2mqtt/light/govee2mqtt_2BEFD0C907BB6BF2/gradient
            # govee2mqtt/light/govee2mqtt_2BEFD0C907BB6BF2/brightness/set

            # Case 1 and 2
            if len(components) >= 4 and "_" in components[-2]:
                vendor, device_id = components[-2].split("_", 1)
                attribute = components[-1]

            # Case 3
            elif len(components) >= 5 and "_" in components[-3]:
                vendor, device_id = components[-3].split("_", 1)
                attribute = components[-2]

            else:
                raise ValueError(
                    f"Malformed topic (expected underscore): {'/'.join(components)}"
                )

            return (vendor, device_id, attribute)

        except Exception as e:
            self.logger.warning(f"Malformed device topic: {components} ({e})")
            return (None, None, None)

    def safe_split_device(self, topic, segment):
        """Split a topic segment into (vendor, device_id) safely."""
        try:
            return segment.split("-", 1)
        except ValueError:
            self.logger.warning(f"Ignoring malformed topic: {topic}")
            return (None, None)

    def is_discovered(self, device_id) -> bool:
        return bool(
            self.states.get(device_id, {}).get("internal", {}).get("discovered", False)
        )

    def set_discovered(self, device_id) -> None:
        self.upsert_state(device_id, internal={"discovered": True})

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        reason_names = [rc.getName() for rc in reason_code_list]
        joined = "; ".join(reason_names) if reason_names else "none"
        self.logger.debug(f"MQTT subscribed (mid={mid}): {joined}")

    def mqtt_safe_publish(self, topic, payload, **kwargs):
        if "component" in payload or "//////" in payload:
            self.logger.warning(
                "Questionable payload includes 'component' or string of slashes - wont't send to HA"
            )
            self.logger.warning(f"topic: {topic}")
            self.logger.warning(f"payload: {payload}")
            raise ValueError(
                "Possible invalid payload. topic: {topic} payload: {payload}"
            )
        try:
            self.mqttc.publish(topic, payload, **kwargs)
        except Exception as e:
            self.logger.warning(f"MQTT publish failed for {topic}: {e}")
