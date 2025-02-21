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
        config = yaml.load(file, Loader=yaml.FullLoader)
except:
    config = {}
    config['mqtt'] = {}
    config['mqtt']['host'] = os.getenv("MQTT_HOST")
    config['mqtt']['qos'] = int(os.getenv("MQTT_QOS") or 0)
    config['mqtt']['port'] = int(os.getenv("MQTT_PORT") or 1883)
    config['mqtt']['username'] = os.getenv("MQTT_USERNAME")
    config['mqtt']['password'] = os.getenv("MQTT_PASSWORD")  # can be None

    config['mqtt']['prefix'] = os.getenv("MQTT_PREFIX")
    config['mqtt']['homeassistant'] = os.getenv("MQTT_HOMEASSISTANT")

    config['mqtt']['tls_enabled'] = os.getenv("MQTT_TLS_ENABLED") == "true"
    config['mqtt']['tls_ca_cert'] = os.getenv("MQTT_TLS_CA_CERT")
    config['mqtt']['tls_cert'] = os.getenv("MQTT_TLS_CERT")
    config['mqtt']['tls_key'] = os.getenv("MQTT_TLS_KEY")

    config['govee'] = {}
    config['govee']['api_key'] = os.getenv("GOVEE_API_KEY")
    config['govee']['device_interval'] = int(os.getenv("GOVEE_DEVICE_INTERVAL"))
    config['govee']['device_boost_interval'] = int(os.getenv("GOVEE_DEVICE_BOOST_INTERVAL"))
    config['govee']['device_list_interval'] = int(os.getenv("GOVEE_LIST_INTERVAL"))

    config['debug'] = True if os.getenv("GOVEE_DEBUG") else False

# fallback defaults
config['mqtt'].setdefault('host','localhost')
config['mqtt'].setdefault('qos', 0)
config['mqtt'].setdefault('port', 1883)
config['mqtt'].setdefault('prefix', 'govee')
config['mqtt'].setdefault('homeassistant', 'homeassistant')
config['govee'].setdefault('device_interval', 30)
config['govee'].setdefault('device_boost_interval', 5)
config['govee'].setdefault('device_list_interval', 300)

if 'debug' in config and config['debug'] is True:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

logging.info('Starting Application')
try:
  GoveeMqtt(config)
except ConnectionError as error:
  log(f"Could not connect to MQTT server: {error}", level="ERROR")
  sys.exit(1)