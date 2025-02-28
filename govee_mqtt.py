import asyncio
from datetime import date
import goveeapi
import json
import paho.mqtt.client as mqtt
import ssl
import time
from util import *
from zoneinfo import ZoneInfo

class GoveeMqtt(object):
    def __init__(self, config):
        self._interrupted = False

        self.timezone = config['timezone']

        self.mqttc = None
        self.mqtt_connect_time = None

        self.mqtt_config = config['mqtt']
        self.govee_config = config['govee']

        self.version = config['version']
        self.service_name = self.mqtt_config['prefix'] + '-service'
        self.device_update_interval = config['govee'].get('device_interval', 30)
        self.device_update_boosted_interval = config['govee'].get('device_boost_interval', 5)
        self.device_list_update_interval = config['govee'].get('device_list_interval', 300)

        self.devices = {}
        self.running = False

        self.boosted = []

        self.data_file = config['configpath'] + '/govee2mqtt.dat'

    async def __aenter__(self):
        # Save signal handlers
        self.original_sigint_handler = signal.getsignal(signal.SIGINT)
        self.original_sigterm_handler = signal.getsignal(signal.SIGTERM)

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Restore original signal handlers
        signal.signal(signal.SIGINT, self.original_sigint_handler)
        signal.signal(signal.SIGTERM, self.original_sigterm_handler)

        if self._interrupted:
            log("Exiting due to signal interrupt", tz=self.timezone)
        else:
            log("Exiting normally", tz=self.timezone)

    def _handle_signal(self, signum, frame):
        self._interrupted = True
        log(f"Signal {signum} received", tz=self.timezone)

    def _handle_interrupt(self):
        sys.exit()

    def __enter__(self):
        self.mqttc_create()
        self.goveec = goveeapi.GoveeAPI(self.govee_config['api_key'], self.timezone)
        self.running = True

        self.restore_state()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        log('Exiting gracefully, saving state and alerting MQTT server', tz=self.timezone)
        self.running = False

        self.save_state()

        if self.mqttc is not None and self.mqttc.is_connected():
            for device_id in self.devices:
                self.publish_attributes(device_id, { 'online': False })
            self.mqttc.disconnect()
            log('Disconnected from MQTT', tz=self.timezone)
        else:
            log('Lost connection to MQTT', tz=self.timezone)

    def save_state(self):
        try:
            state = {
                'api_calls': self.goveec.api_calls,
                'last_call_date': self.goveec.last_call_date,
            }
            with open(self.data_file, 'w') as file:
                json.dump(state, file, indent=4)
        except Exception as err:
            log(f'FAILED TO SAVE STATE: {type(err).__name__} - {err=}', level="ERROR", tz=self.timezone)

    def restore_state(self):
        try:
            with open(self.data_file, 'r') as file:
                state = json.loads(file.read())
                self.goveec.restore_state(state['api_calls'], state['last_call_date'])
        except json.decoder.JSONDecodeError as err:
            log(f'UNABLE TO RESTORE STATE: {err}', level='ERROR', tz=self.timezone)
        except Exception as err:
            log(f'UNABLE TO RESTORE STATE: {type(err).__name__} - {err=}', level='ERROR', tz=self.timezone)

    # MQTT Functions
    ################################
    def mqtt_on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            log(f'MQTT CONNECTION ISSUE ({rc})', level='ERROR', tz=self.timezone)
            exit()
        log('MQTT CONNECTED', level='DEBUG', tz=self.timezone)
        client.subscribe(self.get_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, flags, rc, properties):
        log('MQTT DISCONNECTED', level='DEBUG', tz=self.timezone)
        if time.time() > self.mqtt_connect_time + 10:
            self.mqttc_create()
        else:
            exit()

    def mqtt_on_log(self, client, userdata, paho_log_level, msg):
        level = None
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
            level = 'ERROR'
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_WARNING:
            level = 'WARN'
        if level:
            log(f'MQTT LOG: {msg}', level=level, tz=self.timezone)

    def mqtt_on_message(self, client, userdata, msg):
        topic = msg.topic
        if not msg or not msg.payload:
            return
        log(f'Got message: {topic} - {msg.payload}', tz=self.timezone)
        try:
            payload = json.loads(msg.payload)
        except:
            bytes = msg.payload
            payload = { 'state': bytes.decode('utf8') }

        device_id = topic[(len(self.mqtt_config['prefix']) + 1):-4]

        self.send_command(device_id, payload)

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        rc_list = map(lambda x: x.getName(), reason_code_list)

        log(f'MQTT SUBSCRIBED: reason_codes - {'; '.join(rc_list)}', level='DEBUG', tz=self.timezone)

    # Topic Helpers
    ########################################
    def get_sub_topic(self):
        return "{}/+/set".format(self.mqtt_config['prefix'])

    def get_pub_topic(self, device, attribute):
        return "{}/{}/{}".format(self.mqtt_config['prefix'], device, attribute)

    def get_state_topic(self, device_id):
        return "{}/{}".format(self.mqtt_config['prefix'], device_id)

    def get_device_discovery_topic(self, device_id):
        formatted_device_id = self.mqtt_config["prefix"] + '-' + device_id.replace(':','')
        return "{}/light/{}/config".format(self.mqtt_config['homeassistant'], formatted_device_id)

    def get_homeassistant_discovery_topic(self, device_id, device_type, discovery_name):
        formatted_device_id = self.mqtt_config["prefix"] + '-' + device_id.replace(':','')
        return "{}/{}/{}/{}/config".format(self.mqtt_config['homeassistant'], device_type, formatted_device_id, discovery_name)

    # MQTT Helpers
    #########################################
    def mqttc_create(self):
        self.mqttc = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.service_name,
            clean_session=False,
        )

        if self.mqtt_config.get('tls_enabled'):
            self.mqttcnt.tls_set(
                ca_certs=self.mqtt_config.get('tls_ca_cert'),
                certfile=self.mqtt_config.get('tls_cert'),
                keyfile=self.mqtt_config.get('tls_key'),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            )
        else:
            self.mqttc.username_pw_set(
                username=self.mqtt_config.get('username'),
                password=self.mqtt_config.get('password'),
            )

        self.mqttc.on_connect = self.mqtt_on_connect
        self.mqttc.on_disconnect = self.mqtt_on_disconnect
        self.mqttc.on_message = self.mqtt_on_message
        self.mqttc.on_subscribe = self.mqtt_on_subscribe
        self.mqttc.on_log = self.mqtt_on_log

        self.mqttc.will_set(self.get_state_topic(self.service_name) + '/availability', payload="offline", qos=0, retain=True)

        try:
            self.mqttc.connect(
                self.mqtt_config.get('host'),
                port=self.mqtt_config.get('port'),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            log(f'COULD NOT CONNECT TO MQTT {self.mqtt_config.get("host")}: {error}', level='ERROR', tz=self.timezone)
            exit(1)

    def send_service_discovery(self):
        if 'homeassistant' not in self.mqtt_config:
            return
        service_base = {
            '~': self.get_state_topic(self.service_name), 
            'availability_topic': '~/availability',
            'qos': 0,
            'device': {
                'name': 'govee2mqtt service',
                'identifiers': self.service_name,
                'sw_version': self.version,
                'url': 'https://github.com/weirdtangent/govee2mqtt',
            },
            'schema': 'json',
        }

        self.mqttc.publish(self.get_homeassistant_discovery_topic('service', 'sensor', 'service'), json.dumps(
            service_base | {
                'state_topic': '~',
                'icon': 'mdi:language-python',
                'unique_id': self.service_name,
                'name': 'service',
                'json_attributes_topic': '~',
                'value_template': '{{ value_json.availability }}',
                }
            ),
            retain=True,
        )
        self.mqttc.publish(self.get_homeassistant_discovery_topic('service', 'binary_sensor', 'rate-limited'), json.dumps(
            service_base | {
                'state_topic': '~/api',
                'value_template': '{{ value_json.rate_limited }}',
                'payload_on': 'yes',
                'payload_off': 'no',
                'icon': 'mdi:car-speed-limiter',
                'name': 'rate limited by Govee',
                'unique_id': self.service_name + '_api_rate-limited',
                }
            ),
            retain=True,
        )
        self.mqttc.publish(self.get_homeassistant_discovery_topic('service', 'sensor', 'api-calls'), json.dumps(
            service_base | {
                'state_topic': '~/api',
                'value_template': '{{ value_json.calls }}',
                'icon': 'mdi:numeric',
                'name': 'api calls today',
                'unique_id': self.service_name + '_api_calls',
                }
            ),
            retain=True,
        )

    def send_device_discovery(self, device_id, capabilities):
        if 'homeassistant' not in self.mqtt_config:
            return

        device = self.devices[device_id]
        sku = device['sku']
        device_type = 'sensor' if sku.startswith('H5') else 'light'

        base = {
            'qos': 0,
            'device': {
                'name': device["name"],
                'manufacturer': 'Govee',
                'model': sku,
                'identifiers': self.mqtt_config["prefix"] + '-' + device_id.replace(':',''),
                'via_device': self.service_name,
            },
            'origin': {
                'name': 'govee2mqtt service',
                'sw_version': self.version,
                'url': 'https://github.com/weirdtangent/govee2mqtt',
            },
            '~': self.get_state_topic(device_id),
            'availability_topic': '~/availability',
            'command_topic': '~/set',
            'schema': 'json',
            'unique_id': f'govee_{device_type}_' + device_id.replace(':',''),
        }
        light_base = base | {
            'name': 'Light',
            'supported_color_modes': [],
            'state_topic': '~',
        }
        sensor_base = base | {
            'state_class': 'measurement',
            'state_topic': '~',
        }

        light = light_base
        sensor_type = {}

        for key in capabilities:
            instance = key['instance']
            log(f'FOUND INSTANCE {instance} FOR {device_id}', level='DEBUG', tz=self.timezone)

            capability_type = key['type']

            match capability_type:
                case 'devices.capabilities.online':
                    if key['instance'] == 'online':
                        light['state'] = 'ON' if key['state']['value'] == True else 'OFF'

            match instance:
                case 'brightness':
                    light['supported_color_modes'].append('brightness')
                    light['brightness_scale'] = key['parameters']['range']['max']
                    device['brightness_scale'] = key['parameters']['range']['max']
                case 'powerSwitch':
                    light['supported_color_modes'].append('onoff')
                case 'colorRgb':
                    light['supported_color_modes'].append('rgb')
                case 'colorTemperatureK':
                    light['supported_color_modes'].append('color_temp')
                    light['color_temp_kelvin'] = True
                    light['min_kelvin'] = key['parameters']['range']['min'] or 2000
                    light['max_kelvin'] = key['parameters']['range']['max'] or 6535
                case 'sensorTemperature':
                    sensor_type['temperature'] = sensor_base | {
                        'name': 'Temperature',
                        'device_class': 'temperature',
                        'json_attributes_topic': '~',
                        'value_template': '{{ value_json.temperature }}',
                        'unit_of_measurement': '°F',
                        'unique_id': f'govee_{device_type}_' + device_id.replace(':','') + '_temperature',
                    }
                case 'sensorHumidity':
                    sensor_type['humidity'] = sensor_base | {
                        'name': 'Humidity',
                        'device_class': 'humidity',
                        'json_attributes_topic': '~',
                        'value_template': '{{ value_json.humidity }}',
                        'unit_of_measurement': '%',
                        'unique_id': f'govee_{device_type}_' + device_id.replace(':','') + '_humidity',
                    }
                case _:
                    log(f'INSTANCE {instance} IGNORED', level='DEBUG', tz=self.timezone)

        # Note that if `onoff` or `brightness` are used, that must be the only value in the list.
        # so we'll remove 1 and maybe both, if we have other supported modes
        if 'supported_color_modes' in light and len(light['supported_color_modes']) > 1:
            light['supported_color_modes'].remove('brightness')
            if len(light['supported_color_modes']) > 1:
                light['supported_color_modes'].remove('onoff')

        if device_type == 'light':
            log(f'HOME_ASSISTANT LIGHT: {light}', level='DEBUG', tz=self.timezone)
            self.mqttc.publish(
                self.get_device_discovery_topic(device_id),
                json.dumps(light),
                retain=True
            )
        for sensor in sensor_type:
            log(f'HOME_ASSISTANT SENSOR: {sensor}', level='DEBUG', tz=self.timezone)
            self.mqttc.publish(
                self.get_homeassistant_discovery_topic(device_id, 'sensor', sensor),
                json.dumps(sensor_type[sensor]),
                retain=True
            )

    # Govee Helpers
    ###########################################
    def refresh_device_list(self):
        log(f'Refreshing device list (every {self.device_list_update_interval} sec)', tz=self.timezone)
        self.send_service_discovery()

        devices = self.goveec.get_device_list()
        self.update_service()
        for device in devices:
            device_id = device['device']

            if 'type' in device:
                first = False
                if device_id not in self.devices:
                    first = True
                    self.devices[device_id] = {}
                    self.devices[device_id]['sku'] = device['sku']
                    self.mqttc.will_set(self.get_state_topic(device_id)+'/availability', payload="offline", qos=0, retain=True)

                self.devices[device_id]['name'] = device['deviceName']
                self.devices[device_id]['origin'] = {
                    'name': 'govee2mqtt service',
                    'sw_version': self.version,
                    'url': 'https://github.com/weirdtangent/govee2mqtt',
                }
                self.devices[device_id]['schema'] = 'json'
                
                if first:
                    log(f'Adding new device: {device['deviceName']} ({device_id}) - Govee {device["sku"]}', tz=self.timezone)
                    self.send_device_discovery(device_id, device['capabilities'])
                else:
                    log(f'Updated device: {self.devices[device_id]["name"]}', level='DEBUG', tz=self.timezone)
            else:
                log(f'Saw device, but not supported yet: {device["deviceName"]} ({device_id}) - Govee {device["sku"]}', tz=self.timezone)

    def refresh_all_devices(self):
        log(f'Refreshing {len(self.devices)} device states (every {self.device_update_interval} sec)', tz=self.timezone)

        for device_id in self.devices:
            if device_id not in self.boosted:
                self.refresh_device(device_id)
                # if we just got rate-limited, no need to try any more
                if self.goveec.rate_limited:
                    break

    def refresh_boosted_devices(self):
        if len(self.boosted) > 0:
            log(f'Refreshing {len(self.boosted)} boosted devices (every {self.device_update_boosted_interval} sec)', tz=self.timezone)
        for device_id in self.boosted:
            self.refresh_device(device_id)

    def refresh_device(self, device_id):
        data = self.goveec.get_device(device_id, self.devices[device_id]['sku'])
        self.update_service()

        log(f'REFRESHED {device_id} GOT {data=}', level='DEBUG', tz=self.timezone)
        self.publish_attributes(device_id, data)

    # convert Govee capabilities to MQTT attributes
    def convert_capabilities_to_attributes(self, caps):
        attr = {}

        for key in caps:
            match key:
                case 'online':
                    attr['availability'] = 'online' if caps[key] == True else 'offline'
                case 'powerSwitch':
                    attr['state'] = "ON" if caps[key] == 1 else "OFF"
                case 'colorRgb':
                    attr['color'] = number_to_rgb(caps[key], 16777215)
                case 'sensorTemperature':
                    if not 'telemetry' in attr:
                        attr['telemetry'] = {}
                    attr['telemetry']['temperature'] = caps[key]
                case 'sensorHumidity':
                    if not 'telemetry' in attr:
                        attr['telemetry'] = {}
                    attr['telemetry']['humidity'] = caps[key]
                case _:
                    continue
        return attr

    # convert MQTT attributes to Govee capabilities
    def convert_attributes_to_capabilities(self, attr):
        caps = {}

        for key in attr:
            match key:
                case 'state':
                    caps['powerSwitch'] = {
                        'type': 'devices.capabilities.on_off',
                        'instance': 'powerSwitch',
                        'value': 1 if attr[key] == 'ON' else 0,
                    }
                case 'brightness':
                    caps['brightness'] = {
                        'type': 'devices.capabilities.range',
                        'instance': 'brightness',
                        'value': attr[key],
                    }
                case 'color':
                    caps['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorRgb',
                        'value': rgb_to_number(attr[key]),
                    }
                case 'color_temp':
                    caps['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorTemperatureK',
                        'value': attr[key],
                    }
                case _:
                    continue
        return caps

    def publish_attributes(self, device_id, data):
        changed = False
        attr = data if device_id == self.service_name else self.convert_capabilities_to_attributes(data)

        for key in attr:
            value = json.dumps(attr[key]) if isinstance(attr[key], dict) else attr[key]

            if device_id == self.service_name:
                self.publish_handler(device_id, key, value)
            else:
                old_value = self.devices[device_id][key] if key in self.devices[device_id] else '<undef>'
                old_value = json.dumps(old_value) if isinstance(old_value, dict) else old_value

                if value != old_value:
                    changed = True
                    log(f'DEVICE ATTRIBUTE NEW OR CHANGED: {key} = {value} NOT {old_value}', level='DEBUG', tz=self.timezone)
                    self.publish_handler(device_id, key, value)

        if not changed:
            log(f'DEVICE HAS NOT CHANGED', level='DEBUG', tz=self.timezone)
        if device_id in self.devices:
            self.publish_state_handler(device_id)

        # if we got a change for a boosted device, we can stop boosting it
        if changed and device_id in self.boosted:
           self.boosted.remove(device_id)

    def send_command(self, device_id, data):
        caps = self.convert_attributes_to_capabilities(data)

        sku = self.devices[device_id]['sku']

        if 'brightness' in caps and 'turn' in caps:
            del caps['turn']

        if 'color' in caps and 'turn' in caps:
            del caps['turn']

        log(f'COMMAND {device_id} = {caps}', level='DEBUG', tz=self.timezone)

        first = True
        for key in caps:
            if not first:
                time.sleep(1)
            log(f'CMD DEVICE {self.devices[device_id]["name"]} ({device_id}) {key} = {caps[key]}', level='DEBUG', tz=self.timezone)
            self.goveec.send_command(device_id, sku, caps[key]['type'], caps[key]['instance'], caps[key]['value'])
            self.update_service()
            first = False

        if device_id not in self.boosted:
            self.boosted.append(device_id)

    def publish_handler(self, device_id, attribute, value):
        response = self.mqttc.publish(self.get_pub_topic(device_id, attribute), value, retain=True)
        if device_id in self.devices:
            self.devices[device_id][attribute] = value
        if response.rc != 0:
            log(f'PUBLISH FAILED for {self.devices[device_id]['name']} ({device_id}) SENDING {attribute} = {value} GOT RC: {response.rc}', level='ERROR', tz=self.timezone)


    def publish_state_handler(self, device_id):
        response = self.mqttc.publish(self.get_state_topic(device_id), json.dumps(self.devices[device_id]), retain=True)
        if response.rc != 0:
            log(f'PUBLISH FAILED for {self.devices[device_id]['name']} ({device_id}) SENDING {self.devices[device_id]} GOT RC: {response.rc}', level='ERROR', tz=self.timezone)

    def update_service(self):
        if self.goveec.last_call_date == str(datetime.now(tz=ZoneInfo(self.timezone)).date()):
            self.goveec.increase_api_calls()
        else:
            self.goveec.reset_api_call_count(self.timezone)

        self.publish_attributes(self.service_name, {
            'availability': 'online',
            'config': {
                'device_name': 'govee2mqtt service',
                'sw_version': self.version,
                'prefix': self.mqtt_config['prefix'],
            },
            'origin': {
                'name': 'govee2mqtt service',
                'sw_version': self.version,
                'url': 'https://github.com/weirdtangent/govee2mqtt',
            },
            'api': {
                'calls': self.goveec.api_calls,
                'last_call_date': self.goveec.last_call_date,
                'rate_limited': 'yes' if self.goveec.rate_limited else 'no',
            },
        })

    async def main_loop(self):
        try:
            await asyncio.gather(
                self.device_list_loop(),
                self.device_loop(),
                self.device_boosted_loop(),
            )
        except asyncio.exceptions.CancelledError:
            self.running = False

    async def device_list_loop(self):
        while self.running == True:
            self.refresh_device_list()
            await asyncio.sleep(self.device_list_update_interval)


    async def device_loop(self):
        while self.running == True:
            self.refresh_all_devices()
            await asyncio.sleep(self.device_update_interval)

    async def device_boosted_loop(self):
        while self.running == True:
            self.refresh_boosted_devices()
            await asyncio.sleep(self.device_update_boosted_interval)
