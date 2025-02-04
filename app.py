import yaml
import argparse
import govee_mqtt
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

configdir = args.config
if not configdir.endswith("/"):
    configdir = configdir + "/"

try:
    with open(configdir + "config.yaml") as file:
        config = yaml.load(file, Loader=yaml.FullLoader)
except:
    config['mqtt'] = {}
    config['mqtt']['host'] = os.getenv("MQTT_HOST") or "localhost"
    config['mqtt']['qos'] = int(os.getenv("MQTT_QOS") or 0)
    config['mqtt']['port'] = int(os.getenv("MQTT_PORT") or 1883)
    config['mqtt']['username'] = os.getenv("MQTT_USERNAME")
    config['mqtt']['password'] = os.getenv("MQTT_PASSWORD")  # can be None

    config['mqtt']['prefix'] = os.genenv("MQTT_PREFIX") or "govee"
    config['mqtt']['homeassistant'] = os.getenv("MQTT_HOMEASSISTANT") or "homeassistant"

    config['mqtt']['tls_enabled'] = os.getenv("MQTT_TLS_ENABLED") == "true"
    config['mqtt']['tls_ca_cert'] = os.getenv("MQTT_TLS_CA_CERT")
    config['mqtt']['tls_cert'] = os.getenv("MQTT_TLS_CERT")
    config['mqtt']['tls_key'] = os.getenv("MQTT_TLS_KEY")

    config['govee'] = {}
    config['govee']['api_key'] = os.getenv("GOVEE_API_KEY")
    config['govee']['device_interval'] = os.getenv("GOVEE_DEVICE_INTERVAL") or 30
    config['govee']['device_boost_interval'] = os.getenv("GOVEE_DEVICE_BOOST_INTERVAL") or 5
    config['govee']['device_list_interval'] = os.getenv("GOVEE_LIST_INTERVAL") or 300

    config['debug'] = os.getenv("GOVEE_DEBUG") or False

if 'debug' in config and config['debug'] is True:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

logging.info('Starting Application')
govee_mqtt.GoveeMqtt(config)