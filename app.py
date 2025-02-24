import argparse
from govee_mqtt import GoveeMqtt
import os
import signal
import sys
from util import *
import yaml

is_exiting = False

# Helper functions and callbacks
def signal_handler(sig, frame):
    # exit immediately upon receiving a second SIGINT
    global is_exiting

    if is_exiting:
        os._exit(1)

    is_exiting = True
    exit_gracefully(0)

def exit_gracefully(rc, skip_mqtt=False):
    log(f"Exiting app...")

    # Use os._exit instead of sys.exit to ensure an MQTT disconnect event causes the program to exit correctly as they
    # occur on a separate thread
    os._exit(rc)

def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile("./VERSION"):
        return read_file("./VERSION")

    return read_file("../VERSION")

# Handle interruptions
signal.signal(signal.SIGINT, signal_handler)

# cmd-line args
argparser = argparse.ArgumentParser()
argparser.add_argument(
    "-c",
    "--config",
    required=False,
    help="Directory holding config.yaml or full path to config file",
)
args = argparser.parse_args()

# load config file
configpath = args.config
if configpath:
    if not configpath.endswith(".yaml"):
        if not configpath.endswith("/"):
            configpath += "/"
        configpath += "config.yaml"
    print(f"INFO:root:Trying to load config file {configpath}")
    with open(configpath) as file:
        config = yaml.safe_load(file)
# or check env vars
else:
    print(f"INFO:root:No config file specified, checking ENV")
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

# make sure we at least got the ONE required value
if not 'govee' in config or not 'api_key' in config['govee'] or not config['govee']['api_key']:
    log(f"govee.api_key required in config file or in GOVEE_API_KEY env var", level="ERROR")
    sys.exit(1)

config['version'] = read_version()
log(f"App v{config['version']}")

try:
  GoveeMqtt(config)
except ConnectionError as error:
  log(f"Could not connect to MQTT server: {error}", level="ERROR")
  sys.exit(1)
