import asyncio
import json
import requests
import time
from util import *
import uuid

def slow_down(r):
    sleep_for = (int(r.headers['x-ratelimit-reset']) - int(time.time())) or 60
    log(f'TOO MANY REQUESTS X-RateLimit-Reset: {r.headers['x-ratelimit-reset']} Now: {int(time.time())} Remaining: {sleep_for}', level='ERROR')
    log(f'SORRY, SLEEPING FOR {sleep_for} SEC')
    time.sleep(sleep_for)

DEVICE_URL = 'https://openapi.api.govee.com/router/api/v1/device/state'
DEVICE_LIST_URL = 'https://openapi.api.govee.com/router/api/v1/user/devices'
COMMAND_URL = 'https://openapi.api.govee.com/router/api/v1/device/control'

class GoveeAPI(object):
    def __init__(self, api_key):
        self.api_key = api_key

    def get_device_list(self):
        log('GETTING DEVICE LIST FROM GOVEE', level='DEBUG')
        headers = self.get_headers()

        try:
            r = requests.get(DEVICE_LIST_URL, headers=headers)
            if r.status_code == 429:
                slow_down(r)
                return {}
            if r.status_code >= 400:
                log(f'BAD RESPONSE CODE ({r.status_code}) GETTING DEVICE LIST', level='ERROR')
                return {}
            data = r.json()
        except Exception as error:
            log('ERROR GETTING DEVICE LIST', level='ERROR')
            log(f'{type(error).__name__} - {error}', level='DEBUG')
            return {}

        return data['data']


    def get_device(self, device_id, sku):
        headers = self.get_headers()

        body = {
            'requestId': str(uuid.uuid4()),
            'payload': {
                'sku': sku,
                'device': device_id,
            }
        }

        log(f'GETTING DEVICE FROM GOVEE: {json.dumps(body)}', level='DEBUG')
        try:
            r = requests.post(DEVICE_URL, headers=headers, json=body)
            if r.status_code == 429:
                slow_down(r)
                return {}
            if r.status_code >= 400:
                log(f'BAD RESPONSE CODE ({r.status_code}) GETTING DEVICE', level="ERROR")
                return {}
            data = r.json()
        except:
            log(f'ERROR GETTING DEVICE {device_id}', level='ERROR')
            return {}

        device = data['payload']

        new_capabilities = {}
        for capability in device['capabilities']:
            new_capabilities[capability['instance']] = capability['state']['value']

        return new_capabilities

    def get_headers(self):
        return {
            'Content-Type': "application/json",
            'Govee-API-Key': self.api_key
        }

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
        log(f'SENDING DEVICE CONTROL TO GOVEE: {json.dumps(body)}', level='DEBUG')
        try:
            r = requests.post(COMMAND_URL, headers=headers, json=body)
            if r.status_code == 429:
                slow_down(r)
                return {}
            if r.status_code >= 400:
                log(f'BAD RESPONSE FOR DEVICE COMMAND {data}: RESPONSE CODE: ({r.status_code})', level='ERROR')
                return {}
        except:
            log(f'ERROR SENDING DEVICE COMMAND: {data}', level='ERROR')
            return {}

        log(f'GOVEE DEVICE COMMAND: {json.dumps(body)}, RESPONSE: {r}', level='DEBUG')
