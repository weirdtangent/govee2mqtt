import asyncio
from datetime import datetime
import json
import logging
import requests
from requests.exceptions import RequestException
import time
import uuid
from zoneinfo import ZoneInfo

DEVICE_URL = 'https://openapi.api.govee.com/router/api/v1/device/state'
DEVICE_LIST_URL = 'https://openapi.api.govee.com/router/api/v1/user/devices'
COMMAND_URL = 'https://openapi.api.govee.com/router/api/v1/device/control'

class GoveeAPI(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # we don't want to get the .info HTTP Request logs from Amcrest
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

        self.api_key = config['govee']['api_key']
        self.rate_limited = False
        self.api_calls = 0
        self.last_call_date = None
        self.timezone = config['timezone']

    def restore_state_values(self, api_calls, last_call_date):
        self.api_calls = api_calls
        self.last_call_date = last_call_date
        self.logger.info(f'Restored state to {self.api_calls} for {self.last_call_date}')

    def increase_api_calls(self):
        if not self.last_call_date or self.last_call_date != str(datetime.now(tz=ZoneInfo(self.timezone)).date()):
            self.reset_api_call_count()
        self.api_calls += 1

    def reset_api_call_count(self):
        self.api_calls = 0
        self.last_call_date = str(datetime.now(tz=ZoneInfo(self.timezone)).date())
        self.logger.info('Reset api call count for new day')

    def get_headers(self):
        return {
            'Content-Type': "application/json",
            'Govee-API-Key': self.api_key
        }

    def get_device_list(self):
        self.logger.debug('GETTING DEVICE LIST FROM GOVEE')
        headers = self.get_headers()

        try:
            r = requests.get(DEVICE_LIST_URL, headers=headers)
            self.increase_api_calls()

            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                if r.status_code == 429:
                    self.logger.error(f'RATE-LIMITED GETTING DEVICE LIST')
                else:
                    self.logger.error(f'ERROR ({r.status_code}) GETTING DEVICE LIST')
                return {}
            data = r.json()
            self.logger.debug(f'GOT DEVICE LIST FOR {len(data['data'])} ITEMS')
        except RequestException as err:
            self.logger.error(f'REQUEST PROBLEM, RESTING FOR 10 SEC: {type(err).__name__} - {err=}')
            time.sleep(10)
        except Exception as err:
            self.logger.error(f'ERROR GETTING DEVICE LIST DATA {type(err).__name__} - {err}')
            return {}

        return data['data'] if 'data'in data else {}



    def get_device(self, device_id, sku):
        if not sku:
            return {}

        headers = self.get_headers()
        body = {
            'requestId': str(uuid.uuid4()),
            'payload': {
                'sku': sku,
                'device': device_id,
            }
        }

        try:
            r = requests.post(DEVICE_URL, headers=headers, json=body)
            self.increase_api_calls()

            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                if r.status_code == 429:
                    self.logger.error(f'RATE-LIMITED GETTING DEVICE {(device_id)}')
                else:
                    self.logger.error(f'ERROR ({r.status_code}) GETTING DEVICE ({device_id})')
                return {}
            data = r.json()
            self.logger.debug(f'GOT REFRESH FOR ({device_id})')
        except RequestException as err:
            self.logger.error(f'REQUEST PROBLEM, RESTING FOR 10 SEC: {type(err).__name__} - {err=}')
            time.sleep(10)
        except Exception as err:
            self.logger.error(f'ERROR GETTING DEVICE DATA {type(err).__name__} - {err=}')
            return {}

        new_capabilities = {}
        device = data['payload'] if 'payload' in data else {}

        if 'capabilities' in device:
            for capability in device['capabilities']:
                new_capabilities[capability['instance']] = capability['state']['value']
            # only if we got any `capabilties` back from Govee will we update the `last_update`
            new_capabilities['lastUpdate'] = datetime.now(ZoneInfo(self.timezone))

        return new_capabilities

    def send_command(self, device_id, sku, capability, instance, value):
        body = {
            'requestId': str(uuid.uuid4()),
            'payload': {
                'sku': sku,
                'device': device_id,
                'capability': {
                    'type': capability,
                    'instance': instance,
                    'value': value
                }
            }
        }

        headers = self.get_headers()
        try:
            r = requests.post(COMMAND_URL, headers=headers, json=body)
            self.increase_api_calls()

            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                self.logger.error(f'ERROR SENDING DEVICE COMMAND TO ({device_id}): ({r.status_code}) {type(err).__name__} - {err=}')
                return {}
        except RequestException as err:
            self.logger.error(f'REQUEST PROBLEM, RESTING FOR 10 SEC: {type(err).__name__} - {err=}')
            time.sleep(10)
            return {}
        except Exception as err:
            self.logger.error(f'ERROR SENDING DEVICE COMMAND {type(err).__name__} - {err=}')
            return {}
