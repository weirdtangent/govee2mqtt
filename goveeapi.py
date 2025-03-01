import asyncio
from datetime import date
import json
import requests
from requests.exceptions import RequestException
import time
from util import *
import uuid
from zoneinfo import ZoneInfo

DEVICE_URL = 'https://openapi.api.govee.com/router/api/v1/device/state'
DEVICE_LIST_URL = 'https://openapi.api.govee.com/router/api/v1/user/devices'
COMMAND_URL = 'https://openapi.api.govee.com/router/api/v1/device/control'

class GoveeAPI(object):
    def __init__(self, config):
        self.api_key = config['govee']['api_key']
        self.rate_limited = False
        self.api_calls = 0
        self.last_call_date = ''
        self.timezone = config['timezone']
        self.hide_ts = config['hide_ts'] or False

    def restore_state(self, api_calls, last_call_date):
        self.api_calls = api_calls
        self.last_call_date = last_call_date
        log(f'Restored state to {self.api_calls} for {self.last_call_date}', tz=self.timezone, hide_ts=self.hide_ts)

    def increase_api_calls(self):
        self.api_calls += 1

    def reset_api_call_count(self):
        self.api_calls = 0
        self.last_call_date = str(datetime.now(tz=ZoneInfo(self.timezone)).date())
        log(f'Reset api call count for new day', tz=self.timezone, hide_ts=self.hide_ts)

    def get_headers(self):
        return {
            'Content-Type': "application/json",
            'Govee-API-Key': self.api_key
        }

    def get_device_list(self):
        log('GETTING DEVICE LIST FROM GOVEE', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)
        headers = self.get_headers()

        try:
            r = requests.get(DEVICE_LIST_URL, headers=headers)
            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                if r.status_code == 429:
                    log(f'RATE-LIMITED GETTING DEVICE LIST', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
                else:
                    log(f'ERROR ({r.status_code}) GETTING DEVICE LIST', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
                return {}
            data = r.json()
            log(f'GOT DEVICE LIST FOR {len(data['data'])} ITEMS', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)
        except RequestException as err:
            log(f'REQUEST PROBLEM, RESTING FOR 10 SEC: {type(err).__name__} - {err=}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
            time.sleep(10)
        except Exception as err:
            log(f'ERROR GETTING DEVICE LIST DATA {r.content}', level="ERROR", tz=self.timezone, hide_ts=self.hide_ts)
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
            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                if r.status_code == 429:
                    log(f'RATE-LIMITED GETTING DEVICE {(device_id)}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
                else:
                    log(f'ERROR ({r.status_code}) GETTING DEVICE ({device_id})', level="ERROR", tz=self.timezone, hide_ts=self.hide_ts)
                return {}
            data = r.json()
            log(f'GOT REFRESH ON ({device_id})', level='DEBUG', tz=self.timezone, hide_ts=self.hide_ts)
        except RequestException as err:
            log(f'REQUEST PROBLEM, RESTING FOR 10 SEC: {type(err).__name__} - {err=}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
            time.sleep(10)
        except Exception as err:
            log(f'ERROR GETTING DEVICE DATA {r.content}', level="ERROR", tz=self.timezone, hide_ts=self.hide_ts)
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
            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                log(f'ERROR SENDING DEVICE COMMAND TO ({device_id}): ({r.status_code}) {type(err).__name__} - {err=}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
                return {}
        except RequestException as err:
            log(f'REQUEST PROBLEM, RESTING FOR 10 SEC: {type(err).__name__} - {err=}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
            time.sleep(10)
            return {}
        except Exception as err:
            log(f'ERROR SENDING DEVICE COMMAND {type(err).__name__} - {err=}', level='ERROR', tz=self.timezone, hide_ts=self.hide_ts)
            return {}
