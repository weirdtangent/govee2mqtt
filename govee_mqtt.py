import asyncio
from datetime import datetime
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

        self.mqttc = None
        self.mqtt_connect_time = None

        self.config = config
        self.mqtt_config = config['mqtt']
        self.govee_config = config['govee']
        self.timezone = config['timezone']
        self.version = config['version']
        self.data_file = config['configpath'] + '/govee2mqtt.dat'

        self.device_interval = config['govee'].get('device_interval', 30)
        self.device_boost_interval = config['govee'].get('device_boost_interval', 5)
        self.device_list_interval = config['govee'].get('device_list_interval', 300)
        self.discovery_complete = False

        self.client_id = self.get_new_client_id()
        self.service_name = self.mqtt_config['prefix'] + ' service'
        self.service_slug = self.mqtt_config['prefix'] + '-service'

        self.devices = {} # for storing the device data we send via MQTT
        self.configs = {} # for storing device config that we need to remember: options, scenes, enums, etc
        self.boosted = []

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
                self.publish_device_state(device_id)

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
                self.goveec.restore_state_values(state['api_calls'], state['last_call_date'])
        except Exception as err:
            self.logger.error(f'UNABLE TO RESTORE STATE: {type(err).__name__} - {err}')

    # MQTT Functions ------------------------------------------------------------------------------

    def mqtt_on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            self.logger.error(f'MQTT CONNECTION ISSUE ({rc})')
            exit()
        self.logger.info(f'MQTT connected as {self.client_id}')
        client.subscribe(self.get_device_sub_topic())
        client.subscribe(self.get_attribute_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, flags, rc, properties):
        self.logger.info('MQTT connection closed')

        # if we try to reconnect, lets use a new client_id
        self.client_id = self.get_new_client_id()

        if time.time() > self.mqtt_connect_time + 20:
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

        self.logger.debug(f'Incoming MQTT message for {topic} - {payload}')

        # we might get:
        #   device/component/set
        #   device/component/set/attribute
        #   homeassistant/device/component/set
        #   homeassistant/device/component/set/attribute
        components = topic.split('/')

        try:
            if components[-2] == self.get_component_slug('service'):
                self.handle_service_message(None, payload)
            elif components[-3] == self.get_component_slug('service'):
                self.handle_service_message(components[-1], payload)
            else:
                if components[-1] == 'set':
                    vendor, device_id = components[-2].split('-')
                elif components[-2] == 'set':
                    vendor, device_id = components[-3].split('-')
                    attribute = components[-1]
                else:
                    self.logger.error(f'UNKNOWN MQTT MESSAGE STRUCTURE: {topic}')
                    return
                # of course, we only care about our 'govee-<mac>' component messages
                if vendor != 'govee':
                    return
                # ok, lets format the device_id and send the command to govee
                # for Govee devices, we use the formatted MAC address,
                # so lets convert from the compressed version in the slug
                device_id = ':'.join([device_id[i:i+2] for i in range (0, len(device_id), 2)])

                # if we only got back a scalar value, lets turn it into a dict with
                # the attribute name after `/set/`
                if not isinstance(payload, dict) and attribute:
                    payload = { attribute: payload }

                self.logger.info(f'Got MQTT message for: {self.devices[device_id]["device"]["name"]} - {payload}')
                self.send_command(device_id, payload)
        except Exception as err:
            self.logger.error(f'Failed to understand MQTT message slug ({topic}): {err}, ignoring', exc_info=True)
            return

    def mqtt_on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        rc_list = map(lambda x: x.getName(), reason_code_list)
        self.logger.debug(f'MQTT subscribed: reason_codes - {'; '.join(rc_list)}')

    # MQTT Helpers --------------------------------------------------------------------------------

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

        try:
            self.mqttc.connect(
                self.mqtt_config.get('host'),
                port=self.mqtt_config.get('port'),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            self.logger.error(f'COULD NOT CONNECT TO MQTT {self.mqtt_config.get("host")}: {error}')
            exit(1)

    # MQTT Topics ---------------------------------------------------------------------------------

    def get_new_client_id(self):
        return self.mqtt_config['prefix'] + '-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

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

    # Service Device ------------------------------------------------------------------------------

    def publish_service_state(self):
        self.mqttc.publish(
            self.get_discovery_topic('service','availability'),
            'online',
            qos=self.mqtt_config['qos'],
            retain=True
        )

        self.mqttc.publish(
            self.get_discovery_topic('service','state'),
            json.dumps({
                'state': 'ON',
                'api_calls': self.goveec.get_api_calls(),
                'last_call_date': self.goveec.get_last_call_date(),
                'rate_limited': 'yes' if self.goveec.is_rate_limited() else 'no',
            }),
            qos=self.mqtt_config['qos'],
            retain=True
        )
        self.mqttc.publish(
            self.get_discovery_topic('service','intervals'),
            json.dumps({
                'device_refresh': self.device_interval,
                'device_list_refresh': self.device_list_interval,
                'device_boost_refresh': self.device_boost_interval,
            }),
            qos=self.mqtt_config['qos'],
            retain=True
        )

    def publish_service_discovery(self):
        state_topic = self.get_discovery_topic('service', 'state')
        command_topic = self.get_discovery_topic('service', 'set')
        availability_topic = self.get_discovery_topic('service', 'availability')

        # will_set for service device
        self.mqttc.will_set(availability_topic, 'offline', qos=self.mqtt_config['qos'], retain=True)

        self.mqttc.publish(
            self.get_discovery_topic('service','config'),
            json.dumps({
                'qos': self.mqtt_config['qos'],
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
                'state_topic': state_topic,
                'availability_topic': availability_topic,
                'components': {
                    self.service_slug + '_status': {
                        'name': 'Service',
                        'platform': 'binary_sensor',
                        'schema': 'json',
                        'payload_on': 'ON',
                        'payload_off': 'OFF',
                        'icon': 'mdi:language-python',
                        'state_topic': state_topic,
                        'value_template': '{{ value_json.state }}',
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
                        'state_topic': self.get_discovery_topic('service', 'intervals'),
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
                        'state_topic': self.get_discovery_topic('service', 'intervals'),
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
                        'state_topic': self.get_discovery_topic('service', 'intervals'),
                        'command_topic': self.get_command_topic('service', 'device_boost_refresh'),
                        'value_template': '{{ value_json.device_boost_refresh }}',
                        'unique_id': 'govee_service_device_boost_refresh',
                    },
                },
            }),
            qos=self.mqtt_config['qos'],
            retain=True
        )

    # Govee Helpers -------------------------------------------------------------------------------

    # refresh device list -------------------------------------------------------------------------

    def refresh_device_list(self):
        self.logger.info(f'Refreshing device list from Govee (every {self.device_list_interval} sec)')

        first_time_through = True if len(self.devices) == 0 else False
        if first_time_through:
            # publish state and availability before service device
            self.publish_service_state()
            self.publish_service_discovery()

        devices = self.goveec.get_device_list()
        self.publish_service_state()
        try:
            for device in devices:
                device_id = device['device']
                state_topic = self.get_discovery_topic(device_id, 'state')
                availability_topic = self.get_discovery_topic(device_id, 'availability')
                motion_topic = self.get_discovery_topic(device_id, 'motion')
                command_topic = self.get_discovery_topic(device_id, 'set')

                if 'type' in device:
                    new_device = False
                    if device_id not in self.devices:
                        new_device = True
                        # init new device and minimal setup
                        self.devices[device_id] = {
                            'qos': self.mqtt_config['qos'],
                            'state_topic': state_topic,
                            'availability_topic': availability_topic,
                            'command_topic': command_topic,
                        }
                        self.configs[device_id] = {}

                        # will_sets for devices, in case we go away
                        self.mqttc.will_set(state_topic, None, qos=self.mqtt_config['qos'], retain=True)
                        self.mqttc.will_set(availability_topic, payload='offline', qos=self.mqtt_config['qos'], retain=True)
                        self.mqttc.will_set(motion_topic, None, qos=self.mqtt_config['qos'], retain=True)

                        # publish state and availability before device
                        self.mqttc.publish(self.get_discovery_topic('service','state'), json.dumps({ 'state': None }), qos=self.mqtt_config['qos'], retain=True)
                        self.mqttc.publish(self.get_discovery_topic('service','availability'), 'online', qos=self.mqtt_config['qos'], retain=True)

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
                    self.add_components_to_device(device_id, device['capabilities'])

                    if new_device:
                        self.logger.info(f'Adding device: "{device['deviceName']}" [Govee {device["sku"]}] ({device_id})')

                        # quick set some defaults for state, availability, music if they don't exist yet
                        self.devices[device_id]['state'] = { 'state': None, 'last_update': None }
                        self.devices[device_id]['availability'] = 'online'
                        if self.get_slug(device_id, 'music_mode') in self.devices[device_id]['components']:
                            self.devices[device_id]['music'] = { 'mode': 'Unknown', 'sensitivity': 100 }
                        if self.get_slug(device_id, 'temperature') in self.devices[device_id]['components']:
                            self.devices[device_id]['telemetry'] = { 'temperature': None, 'humidity': None }

                        self.publish_device_state(device_id)
                        self.publish_device_discovery(device_id)
                else:
                    if first_time_through:
                        self.logger.info(f'Saw device, but not supported yet: "{device["deviceName"]}" [Govee {device["sku"]}] ({device_id})')
        except Exception as err:
            self.logger.error(f'Failed to process device list from Govee: {err}', exc_info=True)
            os._exit(1)

        # lets log our first time through and then release the hounds
        if not self.discovery_complete:
            self.logger.info('Device setup and discovery is done')
            self.discovery_complete = True

    # convert Govee device capabilities into MQTT components
    def add_components_to_device(self, device_id, capabilities):
        device = self.devices[device_id]
        config = self.configs[device_id]

        state_topic = self.get_discovery_topic(device_id, 'state')
        availability_topic = self.get_discovery_topic(device_id, 'availability')
        motion_topic = self.get_discovery_topic(device_id, 'motion')
        music_topic = self.get_discovery_topic(device_id, 'music')
        telemetry_topic = self.get_discovery_topic(device_id, 'telemetry')
        command_topic = self.get_discovery_topic(device_id, 'set')

        device_type = 'sensor' if device['device']['model'].startswith('H5') else 'light'

        # we setup a light component to make it easy to add-to
        # as we process capabilities, and then add it to components
        # after the loop
        light = {
            'name': 'Light',
            'platform': 'light',
            'schema': 'json',
            'state_topic': state_topic,
            'command_topic': command_topic,
            'supported_color_modes': [],
            'optimistic': False,
            'unique_id': self.get_slug(device_id, 'light'),
        }
        components = {
            self.get_slug(device_id, 'last_update'): {
                'name': 'Last Update',
                'platform': 'sensor',
                'device_class': 'timestamp',
                'state_topic': state_topic,
                'value_template': '{{ value_json.last_update }}',
                'unique_id': self.get_slug(device_id, 'last_update'),
            }
        }

        try:
            for cap in capabilities:
                match cap['instance']:
                    case 'brightness':
                        light['supported_color_modes'].append('brightness')
                        light['brightness_scale'] = cap['parameters']['range']['max']
                        light['brightness_state'] = state_topic,
                        light['brightness_command'] = command_topic,
                        light['brightness_value_template'] = '{{ value_json.brightness }}'
                    case 'powerSwitch':
                        light['supported_color_modes'].append('onoff')
                    case 'colorRgb':
                        light['supported_color_modes'].append('rgb')
                        light['rgb_state'] = state_topic,
                        light['rgb_command'] = command_topic,
                        light['rgb_value_template'] = '{{ value_json.rgb }}'
                        config['rgb_max'] = cap['parameters']['range']['max'] or 16777215
                    case 'colorTemperatureK':
                        light['supported_color_modes'].append('color_temp')
                        light['color_temp_kelvin'] = True
                        light['min_kelvin'] = cap['parameters']['range']['min'] or 2000
                        light['max_kelvin'] = cap['parameters']['range']['max'] or 9000
                    case 'sensorTemperature':
                        components[self.get_slug(device_id, 'temperature')] = {
                            'name': 'Temperature',
                            'platform': 'sensor',
                            'device_class': 'temperature',
                            'unit_of_measurement': '°F',
                            'state_topic': telemetry_topic,
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
                            'state_topic': telemetry_topic,
                            'value_template': '{{ value_json.humidity }}',
                            'unique_id': self.get_slug(device_id, 'humidity'),
                        }
                    case 'musicMode':
                        # give us a "None" type, especially since Govee
                        # currently doesn't expose the current setting to us
                        music_options = [ 'Unknown' ]
                        # we will remember the options and name->value
                        # translation in a "config" per device since different
                        # devices have different valid values
                        config['music_options'] = { 'Unknown': 0 }

                        for field in cap['parameters']['fields']:
                            match field['fieldName']:
                                case 'musicMode':
                                    for option in field['options']:
                                        music_options.append(option['name'])
                                        config['music_options'][option['name']] = option['value']
                                case 'sensitivity':
                                    music_min = field['range']['min']
                                    music_max = field['range']['max']
                                    music_step = field['range']['precision']
                                    config['music_sensitivity'] = 100

                        components[self.get_slug(device_id, 'music_mode')] = {
                            'name': 'Music Mode',
                            'platform': 'sensor',
                            'device_class': 'enum',
                            'options': music_options,
                            'state_topic': music_topic,
                            'command_topic': self.get_command_topic(device_id, 'music_mode'),
                            'value_template': '{{ value_json.mode }}',
                            'unique_id': self.get_slug(device_id, 'music_mode'),
                        }
                        components[self.get_slug(device_id, 'music_sensitivity')] = {
                            'name': 'Music Sensitivity',
                            'platform': 'number',
                            'schema': 'json',
                            'icon': 'mdi:numeric',
                            'min': music_min,
                            'max': music_max,
                            'step': music_step,
                            'state_topic': music_topic,
                            'command_topic': self.get_command_topic(device_id, 'music_sensitivity'),
                            'value_template': '{{ value_json.sensitivity }}',
                            'unique_id': self.get_slug(device_id, 'music_sensitivity'),
                        }
        except Exception as err:
            self.logger.error(f'Failed to build Govee device components: {err}', exc_info=True)
            os._exit(1)

        # It's a pretty good guess that we have a `light` if we
        # got `supported_color_modes` but note that the docs say:
        #   "if `onoff` or `brightness` are used, that must be the only value in the list."
        # so we'll remove 1 and maybe both when we have other supported color modes
        if len(light['supported_color_modes']) > 0:
            # first, if brightness is supported, lets add the value template
            if 'brightness' in light['supported_color_modes']:
                light['brightness_value_template'] = '{{ value_json.brightness }}'
            # now we can clean up the supported_color_modes
            if len(light['supported_color_modes']) > 1:
                light['supported_color_modes'].remove('onoff')
                if len(light['supported_color_modes']) > 1:
                    light['supported_color_modes'].remove('brightness')

            # ok, now we can add this as a real component to our array
            components[self.get_slug(device_id, 'light')] = light
        
        # pull all components into our device
        device['components'] = components

    def publish_device_state(self, device_id):
        device = self.devices[device_id]

        for topic in ['state','availability','music', 'telemetry']:
            if topic in device:
                payload = json.dumps(device[topic]) if isinstance(device[topic], dict) else device[topic] 
                self.mqttc.publish(self.get_discovery_topic(device_id, topic), payload, qos=self.mqtt_config['qos'], retain=True)

    def publish_device_discovery(self, device_id):
        device = self.devices[device_id]
        payload = json.dumps(device)

        self.mqttc.publish(self.get_discovery_topic(device_id, 'config'), payload, qos=self.mqtt_config['qos'], retain=True)

    # refresh all devices -------------------------------------------------------------------------

    def refresh_all_devices(self):
        # don't let this kick off until we are done with our list
        while not self.discovery_complete:
            time.sleep(1)
        self.logger.info(f'Refreshing all devices from Govee (every {self.device_interval} sec)')

        for device_id in self.devices:
            # break loop if we are ending
            if not self.running:
                break

            if device_id not in self.boosted:
               self.refresh_device(device_id)

    # refresh boosted devices ---------------------------------------------------------------------

    def refresh_boosted_devices(self):
        # don't let this kick off until we are done with our list
        while not self.discovery_complete:
            time.sleep(1)
        if len(self.boosted) > 0:
            for device_id in self.boosted:
                self.refresh_device(device_id)
 
   # other helpers -------------------------------------------------------------------------------

    def refresh_device(self, device_id):
        device = self.devices[device_id]

        data = self.goveec.get_device(device_id, device['device']['model'])
        self.publish_service_state()

        # only need to update MQTT if something changed
        if len(data) > 0:
            self.update_device_components(device_id, data)
            self.publish_device_state(device_id)

        if device_id in self.boosted:
            self.boosted.remove(device_id)

    def update_device_components(self, device_id, data):
        device = self.devices[device_id]
        config = self.configs[device_id]
        light = device['components'][self.get_slug(device_id, 'light')]

        try:
            for key in data:
                match key:
                    case 'online':
                        device['availability'] = 'online' if data[key] == True else 'offline'
                    case 'powerSwitch':
                        device['state']['state'] = 'ON' if data[key] == 1 else 'OFF'
                    case 'brightness':
                        light['brightness'] = data[key]
                    case 'colorRgb':
                        light['color'] = number_to_rgb(data[key], config['rgb_max'])
                    case 'colorTemperatureK':
                        light['color_temp'] = data[key]
                    case 'sensorTemperature':
                        device['telemetry']['temperature'] = data[key]
                    case 'sensorHumidity':
                        device['telemetry']['humidity'] = data[key]
                    case 'musicMode':
                        if isinstance(data[key], dict):
                            device['music']['mode'] = data['musicMode']
                            device['music']['sensitivity'] = data['sensitivity']
                        elif data[key] != '':
                            device['music']['mode'] = find_key_by_value(config['music_options'], data[key])
                    case 'sensitivity':
                        device['music']['sensitivity'] = data[key]
                    case 'lastUpdate':
                        device['state']['last_update'] = data[key].isoformat()
        except Exception as err:
            self.logger.error(f'Failed to update device components: {data} - {err}', exc_info=True)

    # convert MQTT attributes to Govee capabilities
    def build_govee_capabilities(self, device_id, attributes):
        device = self.devices[device_id]
        config = self.configs[device_id]

        capabilities = {}
        for key in attributes:
            match key:
                case 'state':
                    capabilities['powerSwitch'] = {
                        'type': 'devices.capabilities.on_off',
                        'instance': 'powerSwitch',
                        'value': 1 if attributes[key] == 'ON' else 0,
                    }
                case 'brightness':
                    capabilities['brightness'] = {
                        'type': 'devices.capabilities.range',
                        'instance': 'brightness',
                        'value': attributes[key],
                    }
                case 'color':
                    capabilities['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorRgb',
                        'value': rgb_to_number(attributes[key]),
                    }
                case 'color_temp':
                    capabilities['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorTemperatureK',
                        'value': attributes[key],
                    }
                case 'music_sensitivity':
                    mode = device['music']['mode']
                    capabilities['musicMode'] = {
                        'type': 'devices.capabilities.music_setting',
                        'instance': 'musicMode',
                        'value': {
                            'musicMode': config['music_options'][mode],
                            'sensitivity': attributes[key],
                        }
                    }
                case 'music_mode':
                    mode = attributes[key]
                    capabilities['musicMode'] = {
                        'type': 'devices.capabilities.music_setting',
                        'instance': 'musicMode',
                        'value': {
                            'musicMode': config['music_options'][mode],
                            'sensitivity': config['music_sensitivity'],
                        }
                    }

        return capabilities

    # send command to Govee -----------------------------------------------------------------------

    def send_command(self, device_id, data):
        device = self.devices[device_id]
        capabilities = self.build_govee_capabilities(device_id, data)

        # cannot send turn with either brightness or color
        if 'brightness' in capabilities and 'turn' in capabilities:
            del capabilities['turn']
        if 'color' in capabilities and 'turn' in capabilities:
            del capabilities['turn']

        try:
            first = True
            need_boost = False
            for key in capabilities:
                if not first: time.sleep(1)
                self.logger.debug(f'CMD DEVICE: {device['device']['name']} ({device_id}) {key} = {caps[key]}')

                data = self.goveec.send_command(device_id, device['device']['model'], capabilities[key]['type'], capabilities[key]['instance'], capabilities[key]['value'])
                self.publish_service_state()
                first = False

                # no need to boost-refresh if we get the state back on the successful command response
                if len(data) > 0:
                    self.logger.info(f'Got Govee response from command: {data}')
                    self.update_device_components(device_id, data)
                    self.publish_device_state(device_id)

                    # remove from boosted list (if there), since we got a change
                    if device_id in self.boosted:
                        self.boosted.remove(device_id)
                        self.logger.info(f'Refreshed boosted device from Govee: {device["device"]["name"]}')
                else:
                    self.logger.info(f'Did not find changes in Govee response: {data}')
                    need_boost = True

            # if we send a command and did not get a state change back on the response
            # lets boost this device to refresh it, just in case
            if need_boost and device_id not in self.boosted:
                self.boosted.append(device_id)
        except Exception as err:
            self.logger.error(f'Error sending command to Govee, or reading response: {err}')

    def handle_service_message(self, attribute, message):
        match attribute:
            case 'device_refresh':
                self.device_interval = message
                self.logger.info(f'Updated UPDATE_INTERVAL to be {message}')
            case 'device_list_refresh':
                self.device_list_interval = message
                self.logger.info(f'Updated LIST_UPDATE_INTERVAL to be {message}')
            case 'device_boost_refresh':
                self.device_boost_interval = message
                self.logger.info(f'Updated UPDATE_BOOSTED_INTERVAL to be {message}')
            case _:
                self.logger.info(f'IGNORED UNRECOGNIZED govee-service MESSAGE for {attribute}: {message}')
                return
        self.publish_service_state()

    # async functions -----------------------------------------------------------------------------

    async def _handle_signals(self, signame, loop, tasks):
        self.running = False
        self.logger.warn(f'{signame} received, waiting for tasks to cancel...')

        for t in tasks:
            if not t.done():
                t.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        loop.stop()

    async def device_list_loop(self):
        while self.running == True:
            self.refresh_device_list()
            await asyncio.sleep(self.device_list_interval)

    async def device_loop(self):
        while self.running == True:
            self.refresh_all_devices()
            await asyncio.sleep(self.device_interval)

    async def device_boosted_loop(self):
        while self.running == True:
            self.refresh_boosted_devices()
            await asyncio.sleep(self.device_boost_interval)

    # main loop
    async def main_loop(self):
        loop = asyncio.get_running_loop()
        tasks = [
                asyncio.create_task(self.device_list_loop()),
                asyncio.create_task(self.device_loop()),
                asyncio.create_task(self.device_boosted_loop()),
        ]

        # setup signal handling for tasks
        for signame in {'SIGINT','SIGTERM'}:
            loop.add_signal_handler(
                getattr(signal, signame),
                lambda: asyncio.create_task(self._handle_signals(signame, loop, tasks))
            )

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as err:
            self.running = False
            self.logger.error(f'Caught exception: {err}')
