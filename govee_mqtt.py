import asyncio
import goveeapi
import json
from log import log
import paho.mqtt.client as mqtt
import ssl
import time


class GoveeMqtt(object):
    def __init__(self, config):
        self.mqtt_config = config['mqtt']
        self.govee_config = config['govee']
        self.version = config['version']

        self.devices = {}
        self.running = False

        self.boosted = []

        self.mqttc = None
        self.mqtt_connect_time = None

        self.mqttc_create()

        self.goveec = goveeapi.GoveeAPI(self.govee_config['api_key'])

        self.device_update_interval = config['govee'].get('device_interval', 30)
        self.device_update_boosted_interval = config['govee'].get('device_boost_interval', 5)
        self.device_list_update_interval = config['govee'].get('device_list_interval', 300)

        asyncio.run(self.start_govee_loop())

    # MQTT Functions
    ################################
    def mqtt_on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            log("MQTT Connection Issue", level='DEBUG')
            exit()
        log('MQTT CONNECTED', level='DEBUG')
        client.subscribe(self.get_sub_topic())

    def mqtt_on_disconnect(self, client, userdata, rc):
        log("MQTT Disconnected", level='DEBUG')
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
        log(f'GOT MQTT MSG: {device_id}: {payload}')

        self.send_command(device_id, payload)

    def mqtt_on_subscribe(self, *args, **kwargs):
        log('MQTT SUBSCRIBED', level='DEBUG')

    # Topic Helpers
    ########################################
    def get_sub_topic(self):
        return "{}/+/set".format(self.mqtt_config['prefix'])

    def get_pub_topic(self, device, attribute):
        return "{}/{}/{}".format(self.mqtt_config['prefix'], device, attribute)

    def get_state_topic(self, device_id):
        return "{}/{}".format(self.mqtt_config['prefix'], device_id)

    def get_set_topic(self, device_id):
        return "{}/{}/set".format(self.mqtt_config['prefix'], device_id)

    def get_homeassistant_config_topic(self, device_id):
        formatted_device_id = "govee_" + device_id.replace(':','')
        return "{}/light/{}/config".format(self.mqtt_config['homeassistant'], formatted_device_id)

    # MQTT Helpers
    #########################################
    def mqttc_create(self):
        self.mqttc = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="govee2mqtt_broker",
            clean_session=False,
        )

        if self.mqtt_config.get("tls_enabled"):
            self.mqttcnt.tls_set(
                ca_certs=self.mqtt_config.get("tls_ca_cert"),
                certfile=self.mqtt_config.get("tls_cert"),
                keyfile=self.mqtt_config.get("tls_key"),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            )
        else:
            self.mqttc.username_pw_set(
                username=self.mqtt_config.get("username"),
                password=self.mqtt_config.get("password"),
            )

        log("CALLING MQTT CONNECT", level='DEBUG')
        self.mqttc.on_connect = self.mqtt_on_connect
        self.mqttc.on_disconnect = self.mqtt_on_disconnect
        self.mqttc.on_message = self.mqtt_on_message
        self.mqttc.on_subscribe = self.mqtt_on_subscribe
        try:
            self.mqttc.connect(
                self.mqtt_config.get("host"),
                port=self.mqtt_config.get("port"),
                keepalive=60,
            )
            self.mqtt_connect_time = time.time()
            self.mqttc.loop_start()
        except ConnectionError as error:
            log(f"Could not connect to MQTT server {self.mqtt_config.get("host")}: {error}", level='ERROR')
            exit(1)

        self.running = True

    def homeassistant_config(self, device_id):
        if 'homeassistant' not in self.mqtt_config:
            return

        device = self.devices[device_id]
        config = {
            'command_topic': self.get_set_topic(device_id),
            'device': {
                "name": f"Govee {device['sku']} - {device['name']}",
                "manufacturer": "Govee",
                "model": device['sku'],
                "identifiers": "govee_" + device_id.replace(':',''),
                "via_device": f'govee2mqtt v{self.version}',
            },
            'supported_color_modes': [],
            "qos": 0,
            'schema': 'json',
            'state_topic': self.get_state_topic(device_id),
            'json_attributes_topic': self.get_state_topic(device_id),
            'unique_id': "govee_light_" + device_id.replace(':',''),
            "name": "Control"
        }
        for capability in device['capabilities']:
            instance = capability['instance']
            log(f"FOUND INSTANCE {instance} FOR {device_id}", level="DEBUG")
            type = capability['type']
            if type == 'devices.capabilities.range':
                range_min = capability['parameters']['range']['min']
                range_max = capability['parameters']['range']['max']

            if instance == 'brightness':
                config['supported_color_modes'].append('brightness')
                if range_max:
                    config |= {
                        'brightness_scale': range_max,
                    }
                    device['brightness_scale'] = range_max
                
            if instance == 'powerSwitch':
                config['supported_color_modes'].append('onoff')
            
            if instance == 'colorRgb':
                config['supported_color_modes'].append('rgb')

            if instance == 'colorTemperatureK':
                config['supported_color_modes'].append('color_temp')
                config |= {
                    'color_temp_kelvin': True,
                    'min_kelvin': capability['parameters']['range']['min'] or 2000,
                    'max_kelvin': capability['parameters']['range']['max'] or 6535,
                }
        # Note that if onoff or brightness are used, that must be the only value in the list.
        if len(config['supported_color_modes']) > 1:
            config['supported_color_modes'].remove('brightness')
            config['supported_color_modes'].remove('onoff')
        del device['capabilities']

        log(f'HOME_ASSISTANT DEVICE CONFIG: {config}', level='DEBUG')

        self.mqttc.publish(self.get_homeassistant_config_topic(device_id), json.dumps(config), retain=True)

    # Govee Helpers
    ###########################################
    def refresh_device_list(self):
        devices = self.goveec.get_device_list()

        for device in devices:
            device_id = device['device']

            if 'type' in device:
                first = False
                if device_id not in self.devices:
                    first = True
                    self.devices[device_id] = {}
                    self.devices[device_id]['sku'] = device['sku']

                self.devices[device_id]['name'] = device['deviceName']
                self.devices[device_id]['capabilities'] = device['capabilities']

                if first:
                    log(f'NEW DEVICE: {self.devices[device_id]['name']} : ({device_id})')
                    # log(f'NEW DEVICE CONFIG: {self.devices[device_id]}', level='DEBUG')
                    self.homeassistant_config(device_id)
                else:
                    log(f'SAW DEVICE: {device_id}', level='DEBUG')
            else:
                log(f'SAW BUT NOT SUPPORTED YET: {device['sku']} - {device['deviceName']}')

        # log(self.devices, level='DEBUG')

    def refresh_all_devices(self):
        for device_id in self.devices:
            if device_id not in self.boosted:
                self.refresh_device(device_id)

    def refresh_boosted_devices(self):
        for device_id in self.boosted:
            self.refresh_device(device_id)

    def refresh_device(self, device_id):
        sku = self.devices[device_id]['sku']
        data = self.goveec.get_device(device_id, sku)
        # log(f'ORIGINAL DATA: {device_id} {data}', level='DEBUG')

        self.publish_attributes(device_id, data)

    def number_to_rgb(self, number, max_value):
        normalized_value = number / max_value
        r = int((1 - normalized_value) * 255)
        g = int(normalized_value * 255)
        b = int((0.5 - abs(normalized_value - 0.5)) * 2 * 255) if normalized_value > 0.5 else 0
        return { 'r': r, 'g': g, 'b': b }

    def rgb_to_number(self, rgb):
        return int(((rgb['r'] & 0xFF) << 16) + ((rgb['g'] & 0xFF) << 8) + (rgb['b'] & 0xFF))

    def publish_attributes(self, device_id, orig_data):
        changed = False
        data = {}
        for key in orig_data:
            match key:
                case 'powerSwitch':
                    data['state'] = 'ON' if orig_data[key] == 1 else 'OFF'
                case 'brightness':
                    data['brightness'] = orig_data[key]
                case 'brightness_scale':
                    data['brightness_scale'] = orig_data[key]
                case 'colorRgb':
                    data['color'] = self.number_to_rgb(orig_data[key], 16777215)
                case _:
                    continue

        # log(f'CONVERTED DATA: {device_id} {data}', level='DEBUG')
        for attribute in data:
            if attribute not in self.devices[device_id] or self.devices[device_id][attribute] != data[attribute]:
                changed = True
                self.publish_handler(device_id, attribute, data[attribute])

        if changed:
            self.publish_state_handler(device_id)
        if device_id in self.boosted:
            self.boosted.remove(device_id)

    def send_command(self, device_id, data):
        cmd = {}
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
                        'value': self.rgb_to_number(data[key]),
                    }
                case 'color_temp':
                    cmd['colorRgb'] = {
                        'type': 'devices.capabilities.color_setting',
                        'instance': 'colorTemperatureK',
                        'value': data[key],
                    }
                case _:
                    continue;

        log(f'COMMAND {device_id} = {cmd}', level='DEBUG')
        sku = self.devices[device_id]['sku']

        if 'brightness' in cmd and 'turn' in cmd:
            del cmd['turn']

        if 'color' in cmd and 'turn' in cmd:
            del cmd['turn']

        first = True
        for key in cmd:
            if not first:
                time.sleep(1)
            log(f'CMD DEVICE {self.devices[device_id]['name']} ({device_id}) {key} = {cmd[key]}', level='DEBUG')
            self.goveec.send_command(device_id, sku, cmd[key]['type'], cmd[key]['instance'], cmd[key]['value'])
            first = False

        if device_id not in self.boosted:
            self.boosted.append(device_id)

    def publish_handler(self, device_id, attribute, value):
        self.mqttc.publish(self.get_pub_topic(device_id, attribute), json.dumps(value), retain=True)
        self.devices[device_id][attribute] = value
        name = self.devices[device_id]['name']
        log(f"UPDATE: {self.devices[device_id]['name']} ({device_id}): {attribute} = {value}", level='DEBUG')

    def publish_state_handler(self, device_id):
        self.mqttc.publish(self.get_state_topic(device_id), json.dumps(self.devices[device_id]), retain=True)
        log(f"PUBLISHED: {self.devices[device_id]['name']} ({device_id}): {self.devices[device_id]})", level='DEBUG')

    async def start_govee_loop(self):
        await asyncio.gather(
            self.device_list_loop(),
            self.device_loop(),
            self.device_boosted_loop(),
        )

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
