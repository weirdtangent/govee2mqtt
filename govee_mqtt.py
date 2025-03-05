import asyncio
from datetime import date
import govee_api
import json
import logging
import paho.mqtt.client as mqtt
import random
import signal
import ssl
import string
import time
from util import *
from zoneinfo import ZoneInfo

class GoveeMqtt(object):
    def __init__(self, config):
        self.running = False
        self.logger = logging.getLogger(__name__)

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

    async def _handle_sigterm(self, loop, tasks):
        self.running = False
        self.logger.warn('SIGTERM received, waiting for tasks to cancel...')

        for t in tasks:
            t.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        loop.stop()

    def __enter__(self):
        self.mqttc_create()
        self.goveec = govee_api.GoveeAPI(self.config)
        self.restore_state()
        self.running = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        self.logger.info('Exiting gracefully')

        self.save_state()

        if self.mqttc is not None and self.mqttc.is_connected():
            for device_id in self.devices:
                self.devices[device_id]['availability'] = 'offline'
                if 'state' not in self.devices[device_id]:
                    self.devices[device_id]['state'] = {}
                self.publish_device(device_id)

            self.mqttc.disconnect()
        else:
            self.logger.error('Lost connection to MQTT')

    def save_state(self):
        try:
            state = {
                'api_calls': self.goveec.api_calls,
                'last_call_date': self.goveec.last_call_date,
            }
            with open(self.data_file, 'w') as file:
                json.dump(state, file, indent=4)
            self.logger.info(f'Saved state to {self.data_file}')
        except Exception as err:
            self.logger.error(f'FAILED TO SAVE STATE: {type(err).__name__} - {err=}')

    def restore_state(self):
        try:
            with open(self.data_file, 'r') as file:
                state = json.loads(file.read())
                self.goveec.restore_state(state['api_calls'], state['last_call_date'])
        except Exception as err:
            self.logger.error(f'UNABLE TO RESTORE STATE: {type(err).__name__} - {err}')

    # MQTT Functions
    def mqtt_on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            self.logger.error(f'MQTT CONNECTION ISSUE ({rc})')
            exit()
        self.logger.info(f'MQTT connected as {self.client_id}')
        client.subscribe(self.get_device_sub_topic())
        client.subscribe(self.get_attribute_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, flags, rc, properties):
        self.logger.info('MQTT connection closed')
        if time.time() > self.mqtt_connect_time + 10:
            self.mqttc_create()
        else:
            exit()

    def mqtt_on_log(self, client, userdata, paho_log_level, msg):
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
            self.logger.error(f'MQTT LOG: {msg}')
        if paho_log_level == mqtt.LogLevel.MQTT_LOG_WARNING:
            self.logger.warn(f'MQTT LOG: {msg}')

    def mqtt_on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            payload = msg.payload.decode('utf-8')
        except:
            self.logger.error('Failed to understand MQTT message, ignoring')
            return

        self.logger.info(f'Got MQTT message for {topic} - {payload}')

        # we might get:
        # device/component/set
        # device/component/set/attribute
        # homeassistant/device/component/set
        # homeassistant/device/component/set/attribute
        components = topic.split('/')

        # handle this message if it's for us, otherwise pass along to govee API
        try:
            if components[-2] == self.get_component_slug('service'):
                self.handle_service_message(None, payload)
            elif components[-3] == self.get_component_slug('service'):
                self.handle_service_message(components[-1], payload)
            else:
                if components[-1] == 'set':
                    device_id = components[-2].split('-')[1]
                elif components[-2] == 'set':
                    device_id = components[-3].split('-')[1]
                else:
                    self.logger.error(f'UNKNOWN MQTT MESSAGE STRUCTURE: {topic}')
                    return
                # ok, lets format the device_id and send the command to govee
                # for Govee devices, we use the formatted MAC address,
                # so lets convert from the compressed version in the slug
                device_id = ':'.join([device_id[i:i+2] for i in range (0, len(device_id), 2)])
                self.send_command(device_id, payload)
        except Exception as err:
            self.logger.error(f'Failed to understand MQTT message slug ({topic}): {err}, ignoring')
            return

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        rc_list = map(lambda x: x.getName(), reason_code_list)
        self.logger.debug(f'MQTT SUBSCRIBED: reason_codes - {'; '.join(rc_list)}')

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

        self.mqttc.will_set(self.get_discovery_topic('service', 'availability'), payload="offline", qos=self.mqtt_config['qos'], retain=True)

        try:
            self.mqttc.connect(
                self.mqtt_config.get('host'),
                port=self.mqtt_config.get('port'),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            self.logger.info(f'COULD NOT CONNECT TO MQTT {self.mqtt_config.get("host")}: {error}', level='ERROR')
            exit(1)

    # MQTT Topics
    def get_slug(self, device_id, type):
        return f"govee_{device_id.replace(':','')}_{type}"

    def get_device_sub_topic(self):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/+/set"
        return f"{self.mqtt_config['discovery_prefix']}/device/+/set"

    def get_attribute_sub_topic(self):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/+/set"
        return f"{self.mqtt_config['discovery_prefix']}/device/+/set/+"

    def get_component_slug(self, device_id):
        return f"govee-{device_id.replace(':','')}"

    def get_command_topic(self, device_id, attribute_name):
        if attribute_name:
            if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
                return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/set/{attribute_name}"
            return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/set/{attribute_name}"
        else:
            if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
                return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/set"
            return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/set"

    def get_discovery_topic(self, device_id, topic):
        if 'homeassistant' not in self.mqtt_config or self.mqtt_config['homeassistant'] == False:
            return f"{self.mqtt_config['prefix']}/{self.get_component_slug(device_id)}/{topic}"
        return f"{self.mqtt_config['discovery_prefix']}/device/{self.get_component_slug(device_id)}/{topic}"

    # Service Device
    def publish_service_device(self):
        state_topic = self.get_discovery_topic('service', 'state')
        command_topic = self.get_discovery_topic('service', 'set')
        availability_topic = self.get_discovery_topic('service', 'availability')

        self.mqttc.publish(
            self.get_discovery_topic('service','config'),
            json.dumps({
                'qos': 0,
                'state_topic': state_topic,
                'availability_topic': availability_topic,
                'device': {
                    'name': self.service_name,
                    'ids': self.service_slug,
                    'suggested_area': 'House',
                    'manufacturer': 'weirdTangent',
                    'model': self.version,
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
                        'state_topic': state_topic,
                        'value_template': '{{ value_json.status }}',
                        'unique_id': 'govee_service_status',
                    },
                    self.service_slug + '_api_calls': {
                        'name': 'API calls to Govee today',
                        'platform': 'sensor',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'state_topic': state_topic,
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
                        'state_topic': state_topic,
                        'value_template': '{{ value_json.rate_limited }}',
                        'unique_id': 'govee_service_rate_limited',
                    },
                    self.service_slug + '_device_refresh': {
                        'name': 'Device Refresh Interval',
                        'platform': 'number',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'min': 10,
                        'max': 3600,
                        'state_topic': state_topic,
                        'command_topic': self.get_command_topic('service', 'device_refresh'),
                        'value_template': '{{ value_json.device_refresh }}',
                        'unique_id': 'govee_service_device_refresh',
                    },
                    self.service_slug + '_device_list_refresh': {
                        'name': 'Device List Refresh Interval',
                        'platform': 'number',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'min': 10,
                        'max': 3600,
                        'state_topic': state_topic,
                        'command_topic': self.get_command_topic('service', 'device_list_refresh'),
                        'value_template': '{{ value_json.device_list_refresh }}',
                        'unique_id': 'govee_service_device_list_refresh',
                    },
                    self.service_slug + '_device_boost_refresh': {
                        'name': 'Device Boost Refresh Interval',
                        'platform': 'number',
                        'schema': 'json',
                        'icon': 'mdi:numeric',
                        'min': 1,
                        'max': 30,
                        'state_topic': state_topic,
                        'command_topic': self.get_command_topic('service', 'device_boost_refresh'),
                        'value_template': '{{ value_json.device_boost_refresh }}',
                        'unique_id': 'govee_service_device_boost_refresh',
                    },
                },
            }),
            retain=True
        )
        self.update_service_device()

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
                'device_refresh': self.device_update_interval,
                'device_list_refresh': self.device_list_update_interval,
                'device_boost_refresh': self.device_update_boosted_interval,
            }),
            retain=True
        )


    # Govee Helpers
    def refresh_device_list(self):
        self.logger.info(f'Refreshing device list from Govee (every {self.device_list_update_interval} sec)')

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
                    self.mqttc.will_set(self.get_discovery_topic(device_id,'state'), payload=json.dumps({'status': 'offline'}), qos=self.mqtt_config['qos'], retain=True)
                    self.mqttc.will_set(self.get_discovery_topic(device_id,'motion'), payload=None, qos=self.mqtt_config['qos'], retain=True)
                    self.mqttc.will_set(self.get_discovery_topic(device_id,'availability'), payload='offline', qos=self.mqtt_config['qos'], retain=True)

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
                    self.logger.info(f'Adding new device: "{device['deviceName']}" [Govee {device["sku"]}] ({device_id})')
                    self.send_device_discovery(device_id)
                else:
                    self.logger.debug(f'Updated device: {self.devices[device_id]['device']['name']}')
            else:
                if first_time_through:
                    self.logger.info(f'Saw device, but not supported yet: "{device["deviceName"]}" [Govee {device["sku"]}] ({device_id})')

    # convert Govee capabilities to MQTT attributes
    def add_capabilities_to_device(self, device_id, capabilities):
        device = self.devices[device_id]
        device_type = 'sensor' if device['device']['model'].startswith('H5') else 'light'

        # we setup a light component to make it easy to add-to
        # as we process capabilities, and then add it to components
        # after the loop
        light = {
            'name': 'Light',
            'platform': 'light',
            'schema': 'json',
            'state_topic': self.devices[device_id]['state_topic'],
            'command_topic': self.devices[device_id]['command_topic'],
            'supported_color_modes': [],
            'unique_id': self.get_slug(device_id, 'light'),
        }
        components = {
            self.get_slug(device_id, 'last_update'): {
                'name': 'Last Update',
                'platform': 'sensor',
                'device_class': 'timestamp',
                'state_topic': device['state_topic'],
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
                        'value_template': '{{ value_json.humidity }}',
                        'unique_id': self.get_slug(device_id, 'humidity'),
                    }

        # It's a pretty good guess that we have a `light` if we got `supported_color_modes`
        # but note that:
        #   "if `onoff` or `brightness` are used, that must be the only value in the list."
        # so we'll remove 1 and maybe both, if we have other supported color modes
        if len(light['supported_color_modes']) > 0:
            # first, if brightness is supported, lets add the value template
            if 'brightness' in light['supported_color_modes']:
                light['brightness_value_template'] = '{{ value_json.brightness }}'

            if len(light['supported_color_modes']) > 1:
                light['supported_color_modes'].remove('onoff')
                if len(light['supported_color_modes']) > 1:
                    light['supported_color_modes'].remove('brightness')

            # ok, now we can add this as a real component to our device discovery
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
        self.logger.info(f'Refreshing all devices from Govee (every {self.device_update_interval} sec)')

        # refresh devices starting with the device updated the longest time ago
        for each in sorted(self.devices.items(), key=lambda dt: (dt is None, dt)):
            # break loop if we are ending
            if not self.running:
                break
            device_id = each[0]

            if device_id not in self.boosted:
               self.refresh_device(device_id)

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
        # no need to update MQTT if nothing changed
        if len(data) > 0:
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

    def handle_service_message(self, attribute, message):
        match attribute:
            case 'device_refresh':
                self.device_update_interval = message
                self.logger.info(f'Updated UPDATE_INTERVAL to be {message}')
            case 'device_list_refresh':
                self.device_list_update_interval = message
                self.logger.info(f'Updated LIST_UPDATE_INTERVAL to be {message}')
            case 'device_boost_refresh':
                self.device_update_boosted_interval = message
                self.logger.info(f'Updated UPDATE_BOOSTED_INTERVAL to be {message}')
            case _:
                self.logger.info(f'IGNORED UNRECOGNIZED govee-service MESSAGE for {attribute}: {message}')
                return

        self.update_service_device()

    def send_command(self, device_id, data):
        caps = self.convert_attributes_to_capabilities(data)
        sku = self.devices[device_id]['device']['model']

        if 'brightness' in caps and 'turn' in caps:
            del caps['turn']
        if 'color' in caps and 'turn' in caps:
            del caps['turn']

        self.logger.debug(f'COMMAND {device_id} = {caps}')

        first = True
        for key in caps:
            if not first:
                time.sleep(1)
            self.logger.debug(f'CMD DEVICE {self.devices[device_id]['device']['name']} ({device_id}) {key} = {caps[key]}')
            self.goveec.send_command(device_id, sku, caps[key]['type'], caps[key]['instance'], caps[key]['value'])
            self.update_service_device()
            first = False

        if device_id not in self.boosted:
            self.boosted.append(device_id)


    # main loop
    async def main_loop(self):
        loop = asyncio.get_running_loop()
        tasks = [
                asyncio.create_task(self.device_list_loop()),
                asyncio.create_task(self.device_loop()),
                asyncio.create_task(self.device_boosted_loop()),
        ]

        for signame in {'SIGINT','SIGTERM'}:
            loop.add_signal_handler(
                getattr(signal, signame),
                lambda: asyncio.create_task(self._handle_sigterm(loop, tasks))
            )

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass

    async def device_list_loop(self):
        while self.running == True:
            try:
                self.refresh_device_list()
                await asyncio.sleep(self.device_list_update_interval)
            except Exception:
                pass

    async def device_loop(self):
        while self.running == True:
            try:
                self.refresh_all_devices()
                await asyncio.sleep(self.device_update_interval)
            except Exception:
                pass

    async def device_boosted_loop(self):
        while self.running == True:
            try:
                self.refresh_boosted_devices()
                await asyncio.sleep(self.device_update_boosted_interval)
            except Exception:
                pass
