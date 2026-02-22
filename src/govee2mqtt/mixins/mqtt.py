# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
from __future__ import annotations

import asyncio
import json
import ssl
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Coroutine, TypeVar

import paho.mqtt.client as mqtt
from paho.mqtt.client import Client, MQTTMessage, ConnectFlags, DisconnectFlags
from paho.mqtt.enums import CallbackAPIVersion, LogLevel
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

_T = TypeVar("_T")

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class MqttError(ValueError):
    """Raised when the connection to the MQTT server fails"""

    pass


class MqttMixin:
    async def mqttc_create(self: Govee2Mqtt) -> None:
        # Determine MQTT protocol version from config (default to v5)
        protocol_version = self.mqtt_config.get("protocol_version", "5")
        if protocol_version == "3.1.1" or protocol_version == "3":
            self.mqtt_protocol = mqtt.MQTTv311
            self.logger.info("using MQTT protocol version 3.1.1")
        elif protocol_version == "5":
            self.mqtt_protocol = mqtt.MQTTv5
            self.logger.info("using MQTT protocol version 5")
        else:
            self.mqtt_protocol = mqtt.MQTTv5
            self.logger.warning(f"invalid MQTT protocol_version '{protocol_version}', defaulting to version 5")

        self.mqttc = mqtt.Client(
            client_id=self.mqtt_helper.client_id(),
            callback_api_version=CallbackAPIVersion.VERSION2,
            reconnect_on_failure=False,
            protocol=self.mqtt_protocol,
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

        self.mqttc.on_connect = self._wrap_async(self.mqtt_on_connect)
        self.mqttc.on_disconnect = self._wrap_async(self.mqtt_on_disconnect)
        self.mqttc.on_message = self._wrap_async(self.mqtt_on_message)
        self.mqttc.on_subscribe = self._wrap_async(self.mqtt_on_subscribe)
        self.mqttc.on_log = self._wrap_async(self.mqtt_on_log)

        # Define a "last will" message (LWT):
        self.mqttc.will_set(self.mqtt_helper.avty_t("services"), "offline", qos=1, retain=True)

        try:
            host = self.mqtt_config["host"]
            port = self.mqtt_config["port"]
            self.logger.info(f"connecting to mqtt broker at {host}:{port} as {self.client_id}")

            # Only use Properties for MQTTv5
            if self.mqtt_protocol == mqtt.MQTTv5:
                props = Properties(PacketTypes.CONNECT)
                props.SessionExpiryInterval = 0
                self.mqttc.connect(host=host, port=port, keepalive=60, properties=props)
            else:
                self.mqttc.connect(host=host, port=port, keepalive=60)
            self.logger.info(f"successful connection to {host} mqtt broker")

            self.mqtt_connect_time = datetime.now()
            self.mqttc.loop_start()
        except ConnectionError as error:
            self.logger.error(f"failed to connect to mqtt host: {error}")
            self.running = False
            raise SystemExit(1)
        except Exception as error:
            self.logger.error(f"network problem trying to connect to mqtt host: {error}")
            self.running = False
            raise SystemExit(1)

    def _wrap_async(
        self: Govee2Mqtt,
        coro_func: Callable[..., Coroutine[Any, Any, _T]],
    ) -> Callable[..., None]:
        def wrapper(*args: Any, **kwargs: Any) -> None:
            self.loop.call_soon_threadsafe(lambda: asyncio.create_task(coro_func(*args, **kwargs)))

        return wrapper

    async def mqtt_on_connect(
        self: Govee2Mqtt, client: Client, userdata: dict[str, Any], flags: ConnectFlags, reason_code: ReasonCode, properties: Properties | None
    ) -> None:
        if reason_code.value != 0:
            raise MqttError(f"MQTT failed to connect ({reason_code.getName()})")

        # send our helper the client
        self.mqtt_helper.set_client(self.mqttc)

        await self.publish_service_discovery()
        await self.publish_service_availability()
        await self.publish_service_state()

        self.logger.info("subscribing to topics on mqtt")
        client.subscribe("homeassistant/status")
        client.subscribe(f"{self.mqtt_helper.service_slug}/service/+/set")
        client.subscribe(f"{self.mqtt_helper.service_slug}/service/+/command")
        client.subscribe(f"{self.mqtt_helper.service_slug}/+/light/set")
        client.subscribe(f"{self.mqtt_helper.service_slug}/+/light/+/set")
        client.subscribe(f"{self.mqtt_helper.service_slug}/+/switch/+/set")
        client.subscribe(f"{self.mqtt_helper.service_slug}/+/select/+/set")
        client.subscribe(f"{self.mqtt_helper.service_slug}/+/number/+/set")

    async def mqtt_on_disconnect(
        self: Govee2Mqtt, client: Client, userdata: Any, flags: DisconnectFlags, reason_code: ReasonCode, properties: Properties | None
    ) -> None:
        # clear the client on our helper
        self.mqtt_helper.clear_client()

        if reason_code.value != 0:
            self.logger.error(f"mqtt lost connection ({reason_code.getName()})")
        else:
            self.logger.info("closed mqtt connection")

        if self.running and (self.mqtt_connect_time is None or datetime.now() > self.mqtt_connect_time + timedelta(seconds=10)):
            # lets use a new client_id for a reconnect attempt
            self.client_id = self.mqtt_helper.client_id()
            await self.mqttc_create()
        else:
            self.logger.info("mqtt disconnect — stopping service loop")
            self.running = False

    async def mqtt_on_log(self: Govee2Mqtt, client: Client, userdata: Any, paho_log_level: int, msg: str) -> None:
        if paho_log_level == LogLevel.MQTT_LOG_ERR:
            self.logger.error(f"mqtt logged: {msg}")
        if paho_log_level == LogLevel.MQTT_LOG_WARNING:
            self.logger.warning(f"mqtt logged: {msg}")

    async def mqtt_on_message(self: Govee2Mqtt, client: Client, userdata: Any, msg: MQTTMessage) -> None:
        topic = msg.topic
        components = topic.split("/")

        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            try:
                payload = msg.payload.decode("utf-8")
            except Exception as err:
                self.logger.warning(f"failed to decode mqtt payload: {err}")
                return None

        if components[0] == self.mqtt_config["discovery_prefix"]:
            return await self.handle_homeassistant_message(payload)

        if components[0] == self.mqtt_helper.service_slug and components[1] == "service":
            return await self.handle_service_message(components[2], payload)

        if components[0] == self.mqtt_helper.service_slug:
            return await self.handle_device_topic(components, payload)

        self.logger.debug(f"did not process message on mqtt topic: {topic} with {payload}")

    async def handle_homeassistant_message(self: Govee2Mqtt, payload: str) -> None:
        if payload == "online":
            await self.rediscover_all()
            self.logger.info("home Assistant came online — rediscovering devices")

    async def handle_device_topic(self: Govee2Mqtt, components: list[str], payload: Any) -> None:
        parsed = self._parse_device_topic(components)
        if not parsed:
            return

        vendor, device_id, attribute = parsed
        if not vendor or not vendor.startswith(self.mqtt_helper.service_slug):
            self.logger.error(f"ignoring non-Govee device command, got vendor {vendor}")
            return
        if not device_id or not attribute:
            self.logger.error(f"failed to parse device_id and/or payload from mqtt topic components: {components}")
            return
        if not self.devices.get(device_id, None):
            self.logger.warning(f"got mqtt message for unknown device: ({device_id})")
            return

        self.logger.info(f"got message for '{self.get_device_name(device_id)}': {payload}")
        await self.send_command(device_id, attribute, payload)

    def _parse_device_topic(self: Govee2Mqtt, components: list[str]) -> list[str | None] | None:
        """Extract (vendor, device_id, attribute) from an MQTT topic components list (underscore-delimited)."""
        try:
            if components[-1] != "set":
                return None

            # Example topics
            # govee2mqtt/govee2mqtt_2BEFD0C907BB6BF2/light/set
            # govee2mqtt/govee2mqtt_2BEFD0C907BB6BF2/light/rgb_color/set
            # govee2mqtt/govee2mqtt_2BEFD0C907BB6BF2/switch/dreamview/set

            vendor, device_id = components[1].split("_", 1)
            attribute = components[-2]

            return [vendor, device_id, attribute]

        except Exception as e:
            self.logger.warning(f"malformed device topic: {components} ({e})")
            return None

    def safe_split_device(self: Govee2Mqtt, topic: str, segment: str) -> list[str]:
        """Split a topic segment into (vendor, device_id) safely."""
        try:
            return segment.split("-", 1)
        except ValueError:
            self.logger.warning(f"ignoring malformed topic: {topic}")
            return []

    def is_discovered(self: Govee2Mqtt, device_id: str) -> bool:
        return bool(self.states.get(device_id, {}).get("internal", {}).get("discovered", False))

    def set_discovered(self: Govee2Mqtt, device_id: str) -> None:
        self.upsert_state(device_id, internal={"discovered": True})

    async def mqtt_on_subscribe(self: Govee2Mqtt, client: Client, userdata: Any, mid: int, reason_code_list: list[ReasonCode], properties: Properties) -> None:
        reason_names = [rc.getName() for rc in reason_code_list]
        joined = "; ".join(reason_names) if reason_names else "none"
        self.logger.debug(f"mqtt subscribed (mid={mid}): {joined}")
