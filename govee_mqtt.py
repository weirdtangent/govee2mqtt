import asyncio
from datetime import date
import goveeapi
import json
import paho.mqtt.client as mqtt
import ssl
import time
from util import *

class GoveeMqtt(object):
    def __init__(self, config):
        self._interrupted = False

        self.mqttc = None
        self.mqtt_connect_time = None

        self.mqtt_config = config['mqtt']
        self.govee_config = config['govee']

        self.version = config['version']
        self.broker_name = self.mqtt_config['prefix'] + '-broker'
        self.device_update_interval = config['govee'].get('device_interval', 30)
        self.device_update_boosted_interval = config['govee'].get('device_boost_interval', 5)
        self.device_list_update_interval = config['govee'].get('device_list_interval', 300)

        self.devices = {}
        self.running = False

        self.boosted = []

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
            log("Exiting due to signal interrupt")
        else:
            log("Exiting normally")

    def _handle_signal(self, signum, frame):
        self._interrupted = True
        log(f"Signal {signum} received")

    def _handle_interrupt(self):
        sys.exit()

    def __enter__(self):
        self.mqttc_create()
        self.goveec = goveeapi.GoveeAPI(self.govee_config['api_key'])
        self.running = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        log('Exiting gracefully, telling MQTT')
        self.running = False
        if self.mqttc is not None and self.mqttc.is_connected():
            for device_id in self.devices:
                self.publish_attributes(device_id, { 'online': False, 'status': False })
            self.mqttc.disconnect()
            log('Disconnected from MQTT')
        else:
            log('Lost connection to MQTT')

    # MQTT Functions
    ################################
    def mqtt_on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            log(f'MQTT connection issue ({rc})', level='ERROR')
            exit()
        log('MQTT CONNECTED', level='DEBUG')
        client.subscribe(self.get_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, rc):
        log('MQTT DISCONNECTED', level='DEBUG')
        if time.time() > self.mqtt_connect_time + 10:
            self.mqttc_create()
        else:
            exit()

    def mqtt_on_message(self, client, userdata, msg):
        topic = msg.topic
        if not msg or not msg.payload:
            return
        payload = json.loads(msg.payload)
        device_id = topic[(len(self.mqtt_config['prefix']) + 1):-4]
        log(f'Got MQTT message: {device_id}: {payload}')

        self.send_command(device_id, payload)

    def mqtt_on_subscribe(self, *args, **kwargs):
        log('MQTT SUBSCRIBED', level='DEBUG')

    # Topic Helpers
    ########################################
    def get_sub_topic(self):
        return "{}/+/set".format(self.mqtt_config['prefix'])

    def get_pub_topic(self, device, attribute):
        return "{}/{}/{}".format(self.mqtt_config['prefix'], device, attribute)

    def get_sensor_pub_topic(self, device, sensor, attribute):
        return "{}/{}/{}/{}".format(self.mqtt_config['prefix'], device, sensor, attribute)

    def get_state_topic(self, device_id):
        return "{}/{}".format(self.mqtt_config['prefix'], device_id)

    def get_set_topic(self, device_id):
        return "{}/{}/set".format(self.mqtt_config['prefix'], device_id)

    def get_homeassistant_config_topic(self, device_id):
        formatted_device_id = self.mqtt_config["prefix"] + '-' + device_id.replace(':','')
        return "{}/light/{}/config".format(self.mqtt_config['homeassistant'], formatted_device_id)

    def get_homeassistant_sensor_topic(self, device_id, device_type, sensor_name):
        formatted_device_id = self.mqtt_config["prefix"] + '-' + device_id.replace(':','')
        return "{}/{}/{}/{}/config".format(self.mqtt_config['homeassistant'], device_type, formatted_device_id, sensor_name)

    # MQTT Helpers
    #########################################
    def mqttc_create(self):
        self.mqttc = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=self.broker_name,
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

        self.mqttc.will_set(self.get_state_topic(self.broker_name) + '/status', payload="offline", qos=0, retain=True)
        self.mqttc.will_set(self.get_state_topic(self.broker_name) + '/availability', payload="offline", qos=0, retain=True)

        try:
            self.mqttc.connect(
                self.mqtt_config.get('host'),
                port=self.mqtt_config.get('port'),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            log(f'Could not connect to MQTT server {self.mqtt_config.get("host")}: {error}', level='ERROR')
            exit(1)

    def homeassistant_broker_config(self):
        if 'homeassistant' not in self.mqtt_config:
            return
        broker_base = {
            'availability_topic': self.get_state_topic(self.broker_name) + '/availability',
            'state_topic': self.get_state_topic(self.broker_name) + '/status',
            'qos': 0,
            'device': {
                'name': 'govee2mqtt broker',
                'identifiers': self.broker_name,
            },
        }

        self.mqttc.publish(self.get_homeassistant_sensor_topic('broker', 'sensor', 'broker'), json.dumps(
            broker_base | {
                'icon': 'mdi:language-python',
                'unique_id': self.broker_name,
                'name': 'broker',
                }
            ),
            retain=True,
        )
        self.mqttc.publish(self.get_homeassistant_sensor_topic('broker', 'binary_sensor', 'rate-limited'), json.dumps(
            broker_base | {
                'value_template': '{{ value_json.rate_limited }}',
                'payload_on': 'yes',
                'payload_off': 'no',
                'icon': 'mdi:car-speed-limiter',
                'unique_id': self.broker_name + '_api_rate-limited',
                'name': 'rate limited by Govee',
                '~': self.get_state_topic(self.broker_name),
                'stat_t': '~/api',
                }
            ),
            retain=True,
        )
        self.mqttc.publish(self.get_homeassistant_sensor_topic('broker', 'sensor', 'api-calls'), json.dumps(
            broker_base | {
                'value_template': '{{ value_json.calls }}',
                'icon': 'mdi:numeric',
                'unique_id': self.broker_name + '_api_calls',
                'name': 'api calls today',
                '~': self.get_state_topic(self.broker_name),
                'stat_t': '~/api',
                }
            ),
            retain=True,
        )

    def homeassistant_config(self, device_id):
        if 'homeassistant' not in self.mqtt_config:
            return

        device = self.devices[device_id]
        device_type = 'sensor' if device['sku'] == 'H5179' else 'light'

        base = {
            'qos': 0,
            'device': {
                'name': device["name"],
                'manufacturer': 'Govee',
                'model': device['sku'],
                'identifiers': self.mqtt_config["prefix"] + '-' + device_id.replace(':',''),
                'via_device': self.broker_name,
            },
            'availability_topic': self.get_state_topic(device_id) + '/availability',
            'state_topic': self.get_state_topic(device_id) + '/config',
            'command_topic': self.get_set_topic(device_id),
            'json_attributes_topic': self.get_state_topic(device_id),
            'unique_id': f'govee_{device_type}_' + device_id.replace(':',''),
        }
        light_base = base | {
            'name': 'Light',
            'schema': 'json',
            'supported_color_modes': [],
        }
        sensor_base = base | {
            'state_class': 'measurement',
            '~': self.get_state_topic(device_id),
            'stat_t': '~/telemetry',
        }

        light = light_base
        sensor_type = {}

        for capability in device['capabilities']:
            instance = capability['instance']
            log(f'FOUND INSTANCE {instance} FOR {device_id}', level='DEBUG')

            capability_type = capability['type']

            match capability_type:
                case 'devices.capabilities.online':
                    if capability['instance'] == 'online':
                        light['state'] = 'ON' if capability['state']['value'] == True else 'OFF'

            match instance:
                case 'brightness':
                    light['supported_color_modes'].append('brightness')
                    light['brightness_scale'] = capability['parameters']['range']['max']
                    device['brightness_scale'] = capability['parameters']['range']['max']
                case 'powerSwitch':
                    light['supported_color_modes'].append('onoff')
                case 'colorRgb':
                    light['supported_color_modes'].append('rgb')
                case 'colorTemperatureK':
                    light['supported_color_modes'].append('color_temp')
                    light['color_temp_kelvin'] = True
                    light['min_kelvin'] = capability['parameters']['range']['min'] or 2000
                    light['max_kelvin'] = capability['parameters']['range']['max'] or 6535
                case 'sensorTemperature':
                    sensor_type['temperature'] = sensor_base | {
                        'name': 'Temperature',
                        'device_class': 'temperature',
                        'value_template': '{{ value_json.temperature }}',
                        'unit_of_measurement': '°F',
                        'unique_id': f'govee_{device_type}_' + device_id.replace(':','') + '_temperature',
                    }
                case 'sensorHumidity':
                    sensor_type['humidity'] = sensor_base | {
                        'name': 'Humidity',
                        'device_class': 'humidity',
                        'value_template': '{{ value_json.humidity }}',
                        'unit_of_measurement': '%',
                        'unique_id': f'govee_{device_type}_' + device_id.replace(':','') + '_humidity',
                    }

        # Note that if `onoff` or `brightness` are used, that must be the only value in the list.
        # so we'll remove 1 and maybe both, if we have other supported modes
        if 'supported_color_modes' in light and len(light['supported_color_modes']) > 1:
            light['supported_color_modes'].remove('brightness')
            if len(light['supported_color_modes']) > 1:
                light['supported_color_modes'].remove('onoff')
        # lets not send this mess to home assistant
        del device['capabilities']

        if device_type == 'light':
            log(f'HOME_ASSISTANT LIGHT CONFIG: {light}', level='DEBUG')
            self.mqttc.publish(self.get_homeassistant_config_topic(device_id), json.dumps(light), retain=True)
        for sensor in sensor_type:
            log(f'HOME_ASSISTANT SENSOR CONFIG: {sensor}', level='DEBUG')
            self.mqttc.publish(self.get_homeassistant_sensor_topic(device_id, 'sensor', sensor), json.dumps(sensor_type[sensor]), retain=True)

    # Govee Helpers
    ###########################################
    def refresh_device_list(self):
        log(f'Refreshing device list (every {self.device_list_update_interval} sec)')
        self.devices[self.broker_name] = {
            'name': f'{self.mqtt_config['prefix']} broker',
            'sku': 'broker',
        }
        self.homeassistant_broker_config()

        devices = self.goveec.get_device_list()
        self.update_broker()
        for device in devices:
            device_id = device['device']

            if 'type' in device:
                first = False
                if device_id not in self.devices:
                    first = True
                    self.devices[device_id] = {}
                    self.devices[device_id]['sku'] = device['sku']
                    self.mqttc.will_set(self.get_state_topic(device_id)+'/status', payload="offline", qos=0, retain=True)

                self.devices[device_id]['name'] = device['deviceName']
                self.devices[device_id]['capabilities'] = device['capabilities']

                if first:
                    log(f'Adding new device: {device['deviceName']} ({device_id}) - Govee {device["sku"]}')
                    log(f'new device config: {device}', level='DEBUG')
                    self.homeassistant_config(device_id)
                else:
                    log(f'Updated device: {self.devices[device_id]["name"]}', level='DEBUG')
            else:
                log(f'Saw device, but not supported yet: {device["deviceName"]} ({device_id}) - Govee {device["sku"]}')

    def refresh_all_devices(self):
        log(f'Refreshing {len(self.devices)-1} device states (every {self.device_update_interval} sec)')

        for device_id in self.devices:
            if device_id not in self.boosted:
                self.refresh_device(device_id)
                # if we just got rate-limited, no need to try any more
                if self.goveec.rate_limited:
                    break

    def refresh_boosted_devices(self):
        if len(self.boosted) > 0:
          log(f'Refreshing {len(self.boosted)} boosted devices (every {self.device_update_boosted_interval} sec)')
        for device_id in self.boosted:
            self.refresh_device(device_id)

    def refresh_device(self, device_id):
        data = self.goveec.get_device(device_id, self.devices[device_id]['sku'])
        self.update_broker()

        log(f'REFRESHED {device_id} GOT {data=}', level='DEBUG')
        self.publish_attributes(device_id, data)

    def publish_attributes(self, device_id, orig_data):
        # if no data, we were probably rate-limited (and then paused our requests)
        # so nothing to update, but leave in boosted (if there) so it will try again
        if len(orig_data) == 0:
            return

        changed = False
        data = {}
        log(f'PUBLISHING ATTRIBUTES: {orig_data}', level='DEBUG')

        # convert Govee key/values to MQTT
        for key in orig_data:
            match key:
                case 'config' | 'brightness' | 'brightness_scale' | 'api' | 'rate_limited':
                    data[key] = orig_data[key]
                case 'online':
                    data['availability'] = 'online' if orig_data[key] == True else 'offline'
                case 'status':
                    data['status'] = 'online' if orig_data[key] == True else 'offline'
                case 'powerSwitch':
                    data['state'] = 1 if orig_data[key] == 1 else 0
                case 'colorRgb':
                    data['color'] = number_to_rgb(orig_data[key], 16777215)
                case 'sensorTemperature':
                    if not 'telemetry' in data:
                        data['telemetry'] = {}
                    data['telemetry']['temperature'] = orig_data[key]
                case 'sensorHumidity':
                    if not 'telemetry' in data:
                        data['telemetry'] = {}
                    data['telemetry']['humidity'] = orig_data[key]
                case _:
                    continue

        for attribute in data:
            if attribute not in self.devices[device_id] or self.devices[device_id][attribute] != data[attribute]:
                changed = True
                value = json.dumps(data[attribute]) if isinstance(data[attribute], dict) else data[attribute]
                self.publish_handler(device_id, attribute, value)

        if changed:
            self.publish_state_handler(device_id)

        # we got this far, so drop device from boosted list
        if device_id in self.boosted:
           self.boosted.remove(device_id)

    def send_command(self, device_id, data):
        cmd = {}

        # convert MQTT to Govee key/values
        for key in data:
            match key:
                case 'state':
                    cmd['powerSwitch'] = {
                        'type': 'devices.capabilities.on_off',
                        'instance': 'powerSwitch',
                        'value': 1 if data[key] == 'ON' else 0,
                    }
                case 'brightness':
                    cmd['brightness'] = {
                        'type': 'devices.capabilities.range',
                        'instance': 'brightness',
                        'value': data[key],
                    }
                case 'color':
                    cmd['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorRgb',
                        'value': rgb_to_number(data[key]),
                    }
                case 'color_temp':
                    cmd['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorTemperatureK',
                        'value': data[key],
                    }
                case _:
                    continue

        sku = self.devices[device_id]['sku']

        if 'brightness' in cmd and 'turn' in cmd:
            del cmd['turn']

        if 'color' in cmd and 'turn' in cmd:
            del cmd['turn']

        log(f'COMMAND {device_id} = {cmd}', level='DEBUG')

        first = True
        for key in cmd:
            if not first:
                time.sleep(1)
            log(f'CMD DEVICE {self.devices[device_id]["name"]} ({device_id}) {key} = {cmd[key]}', level='DEBUG')
            self.goveec.send_command(device_id, sku, cmd[key]['type'], cmd[key]['instance'], cmd[key]['value'])
            self.update_broker()
            first = False

        if device_id not in self.boosted:
            self.boosted.append(device_id)

    def publish_handler(self, device_id, attribute, value):
        response = self.mqttc.publish(self.get_pub_topic(device_id, attribute), value)
        self.devices[device_id][attribute] = value
        log(f'UPDATED: {self.devices[device_id]['name']} ({device_id}): {attribute} = {value}, RC: {response.rc}', level='DEBUG')
        if response.rc != 0:
            log(f'PUBLISH FAILED for {self.devices[device_id]['name']} ({device_id}) SENDING {attribute} = {value} GOT RC: {response.rc}', level='ERROR')


    def publish_state_handler(self, device_id):
        response = self.mqttc.publish(self.get_state_topic(device_id), json.dumps(self.devices[device_id]))
        log(f'PUBLISHED: {self.devices[device_id]['name']} ({device_id}): {self.devices[device_id]}), RC: {response.rc}', level='DEBUG')
        if response.rc != 0:
            log(f'PUBLISH FAILED for {self.devices[device_id]['name']} ({device_id}) SENDING {attribute} = {value} GOT RC: {response.rc}', level='ERROR')

    def update_broker(self):
        if date.today() == self.goveec.last_call_date:
            self.goveec.increase_api_calls()
        else:
            self.goveec.reset_api_call_count()
        self.publish_attributes(self.broker_name, {
            'online': True,
            'status': True,
            'api': {
                'calls': self.goveec.api_calls,
                'last_call_date': str(self.goveec.last_call_date),
                'rate_limited': 'yes' if self.goveec.rate_limited else 'no',
            },
            'config': {
                'device_name': 'govee2mqtt broker',
                'sw_version': self.version,
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
