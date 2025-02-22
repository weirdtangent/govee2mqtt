import yaml
import argparse
from govee_mqtt import GoveeMqtt
import os

import logging

argparser = argparse.ArgumentParser()
argparser.add_argument(
    "-c",
    "--config",
    required=False,
    help="Directory holding config.yaml and application storage",
)
args = argparser.parse_args()

try:
    configdir = args.config
    if not configdir.endswith("/"):
        configdir = configdir + "/"
    with open(configdir + "config.yaml") as file:
        config = yaml.safe_load(file, Loader=yaml.FullLoader)
except:
    logging.info(f"Failed to load {args.config}config.yml, checking ENV")
    config = {
        'mqtt': {
            'host': os.getenv("MQTT_HOST") or 'localhost',
            'qos': int(os.getenv("MQTT_QOS") or 0),
            'port': int(os.getenv("MQTT_PORT") or 1883),
            'username': os.getenv("MQTT_USERNAME"),
            'password': os.getenv("MQTT_PASSWORD"),  # can be None
            'prefix': os.getenv("MQTT_PREFIX") or 'govee2mqtt',
            'homeassistant': os.getenv("MQTT_HOMEASSISTANT") or 'homeassistant',
            'tls_enabled': os.getenv("MQTT_TLS_ENABLED") == "true",
            'tls_ca_cert': os.getenv("MQTT_TLS_CA_CERT"),
            'tls_cert': os.getenv("MQTT_TLS_CERT"),
            'tls_key': os.getenv("MQTT_TLS_KEY"),
        },
        'govee': {
            'api_key': os.getenv("GOVEE_API_KEY"),
            'device_interval': int(os.getenv("GOVEE_DEVICE_INTERVAL") or 30),
            'device_boost_interval': int(os.getenv("GOVEE_DEVICE_BOOST_INTERVAL") or 5),
            'device_list_interval': int(os.getenv("GOVEE_LIST_INTERVAL") or 3600),
        },
        'debug': True if os.getenv("GOVEE_DEBUG") else False,
    }

if 'debug' in config and config['debug'] is True:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

logging.info('Starting Application')
try:
  GoveeMqtt(config)
except ConnectionError as error:
  logging.error(f"Could not connect to MQTT server: {error}")
  sys.exit(1)
