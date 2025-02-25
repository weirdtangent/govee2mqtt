import asyncio
import json
import requests
import time
from util import *
import uuid

def slow_down(r):
    if 'x-rate-limit-reset' in r.headers:
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
                log(f'RATE-LIMITED BY GOVEE, SLEEP FOR 5 SEC')
                time.sleep(5)
                return {}
            if r.status_code != 200:
                log(f'BAD RESPONSE CODE ({r.status_code}) GETTING DEVICE LIST', level='ERROR')
                return {}
            data = r.json()
        except Exception as err:
            log(f'ERROR GETTING DEVICE LIST ({r.status_code}) {type(err).__name__} - {err=}', level='ERROR')
            log(f'REQUEST WAS: {json.dumps(body)}', level='DEBUG')
            log(f'RESPONSE WAS: {r.headers} {r.content}', level='DEBUG')
            return {}

        log(f'GOT DEVICE LIST: ({r.status_code}) {data}', level='DEBUG')

        return data['data']


    def get_device(self, device_id, sku):
        if sku == 'broker':
            return {
                'online': True,
                'status': True,
            }

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
                log(f'RATE-LIMITED BY GOVEE, SLEEP FOR 5 SEC')
                time.sleep(5)
                return {}
            if r.status_code != 200:
                log(f'ERROR ({r.status_code}) GETTING DEVICE', level="ERROR")
                return {}
            data = r.json()
        except Exception as err:
            log(f'ERROR GETTING DEVICE {device_id} ({r.status_code}) {err=}', level='ERROR')
            log(f'REQUEST WAS: {json.dumps(body)}', level='DEBUG')
            log(f'RESPONSE WAS: {r.headers} {r.content}', level='DEBUG')
            return {}

        log(f'GOT DEVICE: ({r.status_code}) {data}', level='DEBUG')

        device = data['payload']

        new_capabilities = {}
        for capability in device['capabilities']:
            new_capabilities[capability['instance']] = capability['state']['value']

        if len(new_capabilities) == 0:
            log(f'GOT DEVICE FROM GOVEE BUT NO ATTRIBUTES: {device=}')

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
                log(f'RATE-LIMITED BY GOVEE, SLEEP FOR 5 SEC')
                time.sleep(5)
                return {}
            if r.status_code != 200:
                log(f'BAD RESPONSE FOR DEVICE COMMAND {data}: RESPONSE CODE: ({r.status_code})', level='ERROR')
                return {}
        except Exception as err:
            log(f'ERROR SENDING DEVICE COMMAND ({r.status_code}) {type(err).__name__} - {err=}', level='ERROR')
            log(f'REQUEST WAS: {json.dumps(body)}', level='DEBUG')
            log(f'RESPONSE WAS: {r.headers} {r.content}', level='DEBUG')
            return {}

        log(f'SEND COMMAND: ({r.status_code}) {data}', level='DEBUG')
