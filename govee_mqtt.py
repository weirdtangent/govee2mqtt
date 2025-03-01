import asyncio
from datetime import date
import goveeapi
import json
import paho.mqtt.client as mqtt
import random
import ssl
import string
import time
from util import *
from zoneinfo import ZoneInfo

class GoveeMqtt(object):
    def __init__(self, config):
        self._interrupted = False
        self.running = False

        self.timezone = config['timezone']

        self.mqttc = None
        self.mqtt_connect_time = None

        self.config = config
        self.mqtt_config = config['mqtt']
        self.govee_config = config['govee']

        self.client_id = self.mqtt_config['prefix'] + '-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

        self.version = config['version']
        self.hide_ts = config['hide_ts'] or False
        self.device_update_interval = config['govee'].get('device_interval', 30)
        self.device_update_boosted_interval = config['govee'].get('device_boost_interval', 5)
        self.device_list_update_interval = config['govee'].get('device_list_interval', 300)

        self.service_name = self.mqtt_config['prefix'] + ' service'
        self.service_slug = self.mqtt_config['prefix'] + '-service'

        self.devices = {}
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
            log("Exiting due to signal interrupt", tz=self.timezone, hide_ts=self.hide_ts)
        else:
            log("Exiting normally", tz=self.timezone, hide_ts=self.hide_ts)

    def _handle_signal(self, signum, frame):
        self._interrupted = True
        log(f"Signal {signum} received", tz=self.timezone, hide_ts=self.hide_ts)

    def _handle_interrupt(self):
        sys.exit()

    def __enter__(self):
        self.mqttc_create()
        self.goveec = goveeapi.GoveeAPI(self.config)
        self.restore_state()
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        log('Exiting gracefully, saving state and alerting MQTT server', tz=self.timezone, hide_ts=self.hide_ts)

        self.save_state()

        if self.mqttc is not None and self.mqttc.is_connected():
            for device_id in self.devices:
                self.devices[device_id]['availability'] = 'offline'
                if 'state' not in self.devices[device_id]:
                    self.devices[device_id]['state'] = {}
                self.publish_device(device_id)

            self.mqttc.disconnect()
        else:
            log('Lost connection to MQTT', tz=self.timezone, hide_ts=self.hide_ts)

    def save_state(self):
        try:
            state = {
                'api_calls': self.goveec.api_calls,
                'last_call_date': self.goveec.last_call_date,
            }
            with open(self.data_file, 'w') as file:
                json.dump(state, file, indent=4)
        except Exception as err:
            log(f'FAILED TO SAVE STATE: {type(err).__name__} - {err=}', level="ERROR", tz=self.timezone, hide_ts=self.hide_ts)

    def restore_state(self):
        try:
            with open(self.data_file, 'r') as file:
                state = json.loads(file.read())
                self.goveec.restore_state(state['api_calls'], state['last_call_date'])
        except Exception as err:
            log(f'UNABLE TO RESTORE STATE: {type(err).__name__} - {err}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)

    # MQTT Topics
    def get_slug(self, device_id, type):
        return f"govee_{device_id.replace(':','')}_{type}"

    def get_sub_topic(self):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/+/set"
        return f"{self.mqtt_config['discovery_prefix']}/device/+/set"

    def get_discovery_topic(self, device_id, topic):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/govee-{device_id.replace(':','')}/{topic}"
        return f"{self.mqtt_config['discovery_prefix']}/device/govee-{device_id.replace(':','')}/{topic}"

    # MQTT Functions
    def mqtt_on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            log(f'MQTT CONNECTION ISSUE ({rc})', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
            exit()
        log(f'MQTT CONNECTED AS {self.client_id}', tz=self.timezone, hide_ts=self.hide_ts)
        client.subscribe(self.get_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, flags, rc, properties):
        log('MQTT DISCONNECTED', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)
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
            log(f'MQTT LOG: {msg}', level=level, tz=self.timezone, hide_ts=self.hide_ts)

    def mqtt_on_message(self, client, userdata, msg):
        if not msg or not msg.payload:
            return
        topic = msg.topic
        payload = json.loads(msg.payload)
        mac = topic[-20:-4] # strip mac address out of homeassistant/device/govee-9C3BCA3237383387/set
        device_id = ':'.join([mac[i:i+2] for i in range (0, len(mac), 2)])

        log(f'Got MQTT message for {device_id} - {payload}', tz=self.timezone, hide_ts=self.hide_ts)
        self.send_command(device_id, payload)

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        rc_list = map(lambda x: x.getName(), reason_code_list)
        log(f'MQTT SUBSCRIBED: reason_codes - {'; '.join(rc_list)}', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)

    # MQTT Helpers
    def mqttc_create(self):
        self.mqttc = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
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

        # self.mqttc.will_set(self.get_state_topic(self.service_slug) + '/availability', payload="offline", qos=0, retain=True)

        try:
            self.mqttc.connect(
                self.mqtt_config.get('host'),
                port=self.mqtt_config.get('port'),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            log(f'COULD NOT CONNECT TO MQTT {self.mqtt_config.get("host")}: {error}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
            exit(1)

    # Service Device
    def publish_service_device(self):
        self.mqttc.publish(
            self.get_discovery_topic('service','config'),
            json.dumps({
                'qos': 0,
                'state_topic': self.get_discovery_topic('service', 'state'),
                'availability_topic': self.get_discovery_topic('service', 'availability'),
                'device': {
                    'name': self.service_name,
                    'ids': self.service_slug,
                },
                'origin': {
                    'name': self.service_name,
                    'sw_version': self.version,
                    'support_url': 'https://github.com/weirdtangent/govee2mqtt',
                },
                'components': {
                    self.service_slug + '_status': {
                        'name': 'Service',
                        'platform': 'binary_sensor',
                        'schema': 'json',
                        'payload_on': 'online',
                        'payload_off': 'offline',
                        'icon': 'mdi:language-python',
                        'state_topic': self.get_discovery_topic('service', 'state'), 
                        'availability_topic': self.get_discovery_topic('service', 'availability'),
                        'value_template': '{{ value_json.status }}',
                        'unique_id': 'govee_service_status',
                    },
                    self.service_slug + '_api_calls': {
                        'name': 'API calls to Govee today',
                        'platform': 'sensor',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'state_topic': self.get_discovery_topic('service', 'state'), 
                        'availability_topic': self.get_discovery_topic('service', 'availability'),
                        'value_template': '{{ value_json.api_calls }}',
                        'unique_id': 'govee_service_api_calls',
                    },
                    self.service_slug + '_rate_limited': {
                        'name': 'Rate-limited by Govee',
                        'platform': 'binary_sensor',
                        'schema': 'json',
                        'payload_on': 'yes',
                        'payload_off': 'no',
                        'icon': 'mdi:car-speed-limiter',
                        'state_topic': self.get_discovery_topic('service', 'state'),
                        'availability_topic': self.get_discovery_topic('service', 'availability'),
                        'value_template': '{{ value_json.rate_limited }}',
                        'unique_id': 'govee_service_rate_limited',
                    },
                },
            }),
            retain=True
        )

    def update_service_device(self):
        if self.goveec.last_call_date == str(datetime.now(tz=ZoneInfo(self.timezone)).date()):
            self.goveec.increase_api_calls()
        else:
            self.goveec.reset_api_call_count()

        self.mqttc.publish(self.get_discovery_topic('service','availability'), 'online', retain=True)
        self.mqttc.publish(
            self.get_discovery_topic('service','state'),
            json.dumps({
                'status': 'online',
                'api_calls': self.goveec.api_calls,
                'last_call_date': self.goveec.last_call_date,
                'rate_limited': 'yes' if self.goveec.rate_limited == True else 'no',
            }),
            retain=True
        )


    # Govee Helpers
    def refresh_device_list(self):
        log(f'Refreshing device list from Govee (every {self.device_list_update_interval} sec)', tz=self.timezone, hide_ts=self.hide_ts)

        first_time_through = True if len(self.devices) == 0 else False
        if first_time_through:
            self.publish_service_device()

        devices = self.goveec.get_device_list()
        self.update_service_device()
        for device in devices:
            device_id = device['device']

            if 'type' in device:
                first = False
                if device_id not in self.devices:
                    first = True
                    self.devices[device_id] = {}
                    self.devices[device_id]['qos'] = 0
                    self.devices[device_id]['state_topic'] = self.get_discovery_topic(device_id, 'state')
                    self.devices[device_id]['availability_topic'] = self.get_discovery_topic(device_id, 'availability')
                    self.devices[device_id]['command_topic'] = self.get_discovery_topic(device_id, 'set')
                    # self.mqttc.will_set(self.get_state_topic(device_id)+'/availability', payload="offline", qos=0, retain=True)

                self.devices[device_id]['device'] = {
                    'name': device['deviceName'],
                    'manufacturer': 'Govee',
                    'model': device['sku'],
                    'ids': device['device'],
                    'via_device': self.service_slug,
                }
                self.devices[device_id]['origin'] = {
                    'name': self.service_name,
                    'sw_version': self.version,
                    'support_url': 'https://github.com/weirdtangent/govee2mqtt',
                }
                self.add_capabilities_to_device(device_id, device['capabilities'])
                
                if first:
                    log(f'Adding new device: "{device['deviceName']}" [Govee {device["sku"]}] ({device_id})', tz=self.timezone, hide_ts=self.hide_ts)
                    self.send_device_discovery(device_id)
                else:
                    log(f'Updated device: {self.devices[device_id]['device']['name']}', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)
            else:
                if first_time_through:
                    log(f'Saw device, but not supported yet: "{device["deviceName"]}" [Govee {device["sku"]}] ({device_id})', tz=self.timezone, hide_ts=self.hide_ts)

    # convert Govee capabilities to MQTT attributes
    def add_capabilities_to_device(self, device_id, capabilities):
        device = self.devices[device_id]
        device_type = 'sensor' if device['device']['model'].startswith('H5') else 'light'

        light = { 'supported_color_modes': [] }
        components = {
            self.get_slug(device_id, 'last_update'): {
                'name': 'Last Update',
                'platform': 'sensor',
                'device_class': 'timestamp',
                'state_topic': device['state_topic'],
                'availability_topic': device['availability_topic'],
                'value_template': '{{ value_json.last_update }}',
                'unique_id': self.get_slug(device_id, 'last_update'),
            }
        }

        for cap in capabilities:
            match cap['instance']:
                case 'brightness':
                    light['supported_color_modes'].append('brightness')
                    light['brightness_scale'] = cap['parameters']['range']['max']
                case 'powerSwitch':
                    light['supported_color_modes'].append('onoff')
                case 'colorRgb':
                    light['supported_color_modes'].append('rgb')
                case 'colorTemperatureK':
                    light['supported_color_modes'].append('color_temp')
                    light['color_temp_kelvin'] = True
                    light['min_kelvin'] = cap['parameters']['range']['min'] or 2000
                    light['max_kelvin'] = cap['parameters']['range']['max'] or 6535
                case 'sensorTemperature':
                    components[self.get_slug(device_id, 'temperature')] = {
                        'name': 'Temperature',
                        'platform': 'sensor',
                        'device_class': 'temperature',
                        'unit_of_measurement': '°F',
                        'state_topic': device['state_topic'],
                        'availability_topic': device['availability_topic'],
                        'value_template': '{{ value_json.temperature }}',
                        'unique_id': self.get_slug(device_id, 'temperature')
                    }
                case 'sensorHumidity':
                    components[self.get_slug(device_id, 'humidity')] = {
                        'name': 'Humidity',
                        'platform': 'sensor',
                        'state_class': 'measurement',
                        'device_class': 'humidity',
                        'unit_of_measurement': '%',
                        'state_topic': device['state_topic'],
                        'availability_topic': device['availability_topic'],
                        'value_template': '{{ value_json.humidity }}',
                        'unique_id': self.get_slug(device_id, 'humidity'),
                    }

        # does this look and smell like a light?
        if len(light['supported_color_modes']) > 0:
            # Note that if `onoff` or `brightness` are used, that must be the only value in the list.
            # so we'll remove 1 and maybe both, if we have other supported color modes
            if len(light['supported_color_modes']) > 1:
                light['supported_color_modes'].remove('onoff')
                if len(light['supported_color_modes']) > 1:
                    light['supported_color_modes'].remove('brightness')
            light['name'] = 'Light'
            light['platform'] = 'light'
            light['schema'] = 'json'
            light['state_topic'] = self.devices[device_id]['state_topic']
            light['availability_topic'] = self.devices[device_id]['availability_topic']
            light['command_topic'] = self.devices[device_id]['command_topic']
            light['unique_id'] = self.get_slug(device_id, 'light')

            if 'brightness' in light['supported_color_modes']:
                light['brightness_value_template'] = '{{ value_json.brightness }}'

            components[self.get_slug(device_id, 'light')] = light
        
        # since we always add `last_update` this should always be true
        if len(components) > 0:
            device['components'] = components

    def update_capabilities_on_device(self, device_id, capabilities):
        device = self.devices[device_id]

        for key in capabilities:
            match key:
                case 'online':
                    device['availability'] = 'online' if capabilities[key] == True else 'offline'
                case 'powerSwitch':
                    device['state']['state'] = 'ON' if capabilities[key] == 1 else 'OFF'
                case 'brightness':
                    device['state']['brightness'] = capabilities[key]
                case 'colorRgb':
                    device['state']['color'] = number_to_rgb(capabilities[key], 16777215)
                case 'colorTemperatureK':
                    device['state']['color_temp'] = capabilities[key]
                case 'sensorTemperature':
                    device['state']['temperature'] = capabilities[key]
                case 'sensorHumidity':
                    device['state']['humidity'] = capabilities[key]
                case 'lastUpdate' if isinstance(capabilities[key], datetime):
                    device['state']['last_update'] = capabilities[key].isoformat()

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

    def send_device_discovery(self, device_id):
        device = self.devices[device_id]
        self.mqttc.publish(self.get_discovery_topic(device_id, 'config'), json.dumps(device), retain=True)

        self.devices[device_id]['state'] = {}
        self.devices[device_id]['availability'] = 'online'

        self.publish_device(device_id)

    def refresh_all_devices(self):
        log(f'Refreshing all devices from Govee (every {self.device_update_interval} sec)', tz=self.timezone, hide_ts=self.hide_ts)

        # refresh devices starting with the device updated the longest time ago
        for each in sorted(self.devices.items(), key=lambda dt: (dt is None, dt)):
            device_id = each[0]

            # all just to format the log record
            last_updated = self.devices[device_id]['state']['last_update'] if 'last_update' in self.devices[device_id]['state'] else 'server started'
            last_updated = last_updated[:19].replace('T',' ')

            log(f'Refreshing device "{self.devices[device_id]['device']['name']} ({device_id})", not updated since: {last_updated}', hide_ts=self.hide_ts)
            if device_id not in self.boosted:
               self.refresh_device(device_id)

    def sort_by_lastupdated(self, device):
        log(device, hide_ts=self.hide_ts)
        return (device.state.last_update is None, device.state.last_update)

    def refresh_boosted_devices(self):
        if len(self.boosted) > 0:
            for device_id in self.boosted:
                self.refresh_device(device_id)

    def refresh_device(self, device_id):
        # don't refresh the device until it has been published in device discovery
        # and we can tell because it will have a `state` once it has been
        if 'state' not in self.devices[device_id]:
            return
        data = self.goveec.get_device(device_id, self.devices[device_id]['device']['model'])
        self.update_service_device()
        self.update_capabilities_on_device(device_id, data)
        self.publish_device(device_id)

    def publish_device(self, device_id):
        self.mqttc.publish(
            self.get_discovery_topic(device_id,'state'),
            json.dumps(self.devices[device_id]['state']),
            retain=True
        )
        self.mqttc.publish(
            self.get_discovery_topic(device_id,'availability'),
            self.devices[device_id]['availability'],
            retain=True
        )

    def send_command(self, device_id, data):
        caps = self.convert_attributes_to_capabilities(data)
        sku = self.devices[device_id]['device']['model']

        if 'brightness' in caps and 'turn' in caps:
            del caps['turn']
        if 'color' in caps and 'turn' in caps:
            del caps['turn']

        log(f'COMMAND {device_id} = {caps}', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)

        first = True
        for key in caps:
            if not first:
                time.sleep(1)
            log(f'CMD DEVICE {self.devices[device_id]['device']['name']} ({device_id}) {key} = {caps[key]}', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)
            self.goveec.send_command(device_id, sku, caps[key]['type'], caps[key]['instance'], caps[key]['value'])
            self.update_service_device()
            first = False

        if device_id not in self.boosted:
            self.boosted.append(device_id)


    # main loop
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
