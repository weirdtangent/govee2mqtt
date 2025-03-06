import asyncio
import argparse
from govee_mqtt import GoveeMqtt
import logging
import os
import sys
import time
from util import *
import yaml

# Let's go!
version = read_version()

# Cmd-line args
argparser = argparse.ArgumentParser()
argparser.add_argument(
    '-c',
    '--config',
    required=False,
    help='Directory holding config.yaml or full path to config file',
)
args = argparser.parse_args()

# Setup config from yaml file or env
configpath = args.config or '/config'
try:
    if not configpath.endswith('.yaml'):
        if not configpath.endswith('/'):
            configpath += '/'
        configfile = configpath + 'config.yaml'
    with open(configfile) as file:
        config = yaml.safe_load(file)
    config['config_path'] = configpath
    config['config_from'] = 'file'
except:
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
        'hide_ts': True if os.getenv('HIDE_TS') else False,
        'timezone': os.getenv('TZ'),
        'config_from': 'env',
    }
config['version'] = version
config['configpath'] = os.path.dirname(configpath)
if 'timezone' not in config: config['timezone'] = 'UTC'
if 'debug' not in config: config['debug'] = os.getenv('DEBUG') or False

# Setup logging
logging.basicConfig(
    format = '%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s' if config['hide_ts'] == False else '[%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO if config['debug'] == False else logging.DEBUG
)
logger = logging.getLogger(__name__)
logger.info(f'Starting: govee2mqtt v{version}')
logger.info(f'Config loaded from {config["config_from"]}')

# Check for required config properties
if not 'govee' in config or not 'api_key' in config['govee'] or not config['govee']['api_key']:
    logger.error('`govee.api_key` required in config file or in GOVEE_API_KEY env var')
    exit(1)

# Go!
with GoveeMqtt(config) as mqtt:
    asyncio.run(mqtt.main_loop())
