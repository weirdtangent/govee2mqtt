# copy, modify, merge, publish, distribute, and sell copies of the software,
# with the requirement to include the original copyright notice and this
# permission notice in all copies or substantial portions of the software.
#
# The software is provided 'as is', without any warranty.

from datetime import datetime
import logging
import requests
from requests.exceptions import RequestException
import uuid
from zoneinfo import ZoneInfo

DEVICE_URL = 'https://openapi.api.govee.com/router/api/v1/device/state'
DEVICE_LIST_URL = 'https://openapi.api.govee.com/router/api/v1/user/devices'
COMMAND_URL = 'https://openapi.api.govee.com/router/api/v1/device/control'

class GoveeAPI(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # we don't want to get this mess of deeper-level logging
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

        self.api_key = config['govee']['api_key']
        self.rate_limited = False
        self.api_calls = 0
        self.last_call_date = None
        self.timezone = config['timezone']

    def restore_state_values(self, api_calls, last_call_date):
        self.api_calls = api_calls
        self.last_call_date = last_call_date

    def increase_api_calls(self):
        if not self.last_call_date or self.last_call_date != str(datetime.now(tz=ZoneInfo(self.timezone)).date()):
            self.reset_api_call_count()
        self.api_calls += 1

    def reset_api_call_count(self):
        self.api_calls = 0
        self.last_call_date = str(datetime.now(tz=ZoneInfo(self.timezone)).date())
        self.logger.info('Reset api call count for new day')

    def get_api_calls(self):
        return self.api_calls

    def get_last_call_date(self):
        return self.last_call_date

    def is_rate_limited(self):
        return self.rate_limited
        return self.rate_limited

    def get_headers(self):
        return {
            'Content-Type': "application/json",
            'Govee-API-Key': self.api_key
        }

    def get_device_list(self):
        headers = self.get_headers()

        try:
            r = requests.get(DEVICE_LIST_URL, headers=headers)
            self.increase_api_calls()

            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                if r.status_code == 429:
                    self.logger.error('Rate-limited by Govee getting device list')
                else:
                    self.logger.error(f'Error ({r.status_code}) getting device list')
                return {}
            data = r.json()

        except RequestException:
            self.logger.error('Request error communicating with Govee for device list')
            return {}
        except Exception:
            self.logger.error('Error communicating with Govee for device list')
            return {}

        return data['data'] if 'data' in data else {}

    def get_device(self, device_id, sku):
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
                    self.logger.error(f'Rate-limited by Govee getting device ({device_id})')
                else:
                    self.logger.error(f'Error ({r.status_code}) getting device ({device_id})')
                return {}
            data = r.json()
        except RequestException:
            self.logger.error(f'Request error communicating with Govee for device ({device_id})')
            return {}
        except Exception:
            self.logger.error(f'Error communicating with Govee for device ({device_id})')
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
        headers = self.get_headers()
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

        try:
            r = requests.post(COMMAND_URL, headers=headers, json=body)
            self.increase_api_calls()

            self.rate_limited = r.status_code == 429
            if r.status_code != 200:
                if r.status_code == 429:
                    self.logger.error(f'Rate-limited by Govee sending command to device ({device_id})')
                else:
                    self.logger.error(f'Error ({r.status_code}) sending command to device ({device_id})')
                return {}
            data = r.json()
            self.logger.debug(f'Raw response from Govee: {data}')
        except RequestException:
            self.logger.error(f'Request error communicating with Govee sending command to device ({device_id})')
            return {}
        except Exception:
            self.logger.error(f'Error communicating with Govee sending command to device ({device_id})')
            return {}

        new_capabilities = {}
        try:
            if 'capability' in data and 'state' in data['capability'] and data['capability']['state']['status'] == 'success':
                capability = data['capability']
                if isinstance(capability['value'], dict):
                    for key in capability['value']:
                        new_capabilities[key] = capability['value'][key]
                else:
                    new_capabilities[capability['instance']] = capability['value']

                # only if we got any `capabilties` back from Govee will we update the `last_update`
                new_capabilities['lastUpdate'] = datetime.now(ZoneInfo(self.timezone))
        except Exception:
            self.logger.error(f'Failed to process response sending command to device ({device_id})')
            return {}

        return new_capabilities
