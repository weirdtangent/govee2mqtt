import asyncio
import argparse
from govee_mqtt import GoveeMqtt
import os
import sys
import time
from util import *
import yaml

# Helper functions and callbacks
def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile('./VERSION'):
        return read_file('./VERSION')

    return read_file('../VERSION')

# Let's go!
version = read_version()
log(f'Starting: govee2mqtt v{version}')

# cmd-line args
argparser = argparse.ArgumentParser()
argparser.add_argument(
    '-c',
    '--config',
    required=False,
    help='Directory holding config.yaml or full path to config file',
)
args = argparser.parse_args()

# load config file
configpath = args.config or '/config'
try:
    if not configpath.endswith('.yaml'):
        if not configpath.endswith('/'):
            configpath += '/'
        configfile = configpath + 'config.yaml'
    with open(configfile) as file:
        config = yaml.safe_load(file)
    log(f'Reading config file {configpath}')
    config['config_from'] = 'file'
    config['config_path'] = configpath
except:
    log(f'config.yaml not found, checking ENV')
    config = {
        'mqtt': {
            'host': os.getenv('MQTT_HOST') or 'localhost',
            'qos': int(os.getenv('MQTT_QOS') or 0),
            'port': int(os.getenv('MQTT_PORT') or 1883),
            'username': os.getenv('MQTT_USERNAME'),
            'password': os.getenv('MQTT_PASSWORD'),  # can be None
            'tls_enabled': os.getenv('MQTT_TLS_ENABLED') == 'true',
            'tls_ca_cert': os.getenv('MQTT_TLS_CA_CERT'),
            'tls_cert': os.getenv('MQTT_TLS_CERT'),
            'tls_key': os.getenv('MQTT_TLS_KEY'),
            'prefix': os.getenv('MQTT_PREFIX') or 'govee2mqtt',
            'homeassistant': os.getenv('MQTT_HOMEASSISTANT') == True,
            'discovery_prefix': os.getenv('MQTT_DISCOVERY_PREFIX') or 'homeassistant',
        },
        'govee': {
            'api_key': os.getenv('GOVEE_API_KEY'),
            'device_interval': int(os.getenv('GOVEE_DEVICE_INTERVAL') or 30),
            'device_boost_interval': int(os.getenv('GOVEE_DEVICE_BOOST_INTERVAL') or 5),
            'device_list_interval': int(os.getenv('GOVEE_LIST_INTERVAL') or 3600),
        },
        'debug': True if os.getenv('GOVEE_DEBUG') else False,
        'config_from': 'env',
        'timezone': os.getenv('TZ'),
    }

config['version'] = version
config['configpath'] = os.path.dirname(configpath)

# make sure we at least got the TWO required values
if not 'govee' in config or not 'api_key' in config['govee'] or not config['govee']['api_key']:
    log('`govee.api_key` required in config file or in GOVEE_API_KEY env var', level='ERROR')
    exit(1)

if not 'timezone' in config:
    log('`timezone` required in config file or in TZ env var', level='ERROR', tz=timezone)
    exit(1)
else:
    log(f'TIMEZONE set as {config["timezone"]}', tz=config["timezone"])

with GoveeMqtt(config) as mqtt:
    asyncio.run(mqtt.main_loop())