# Environment Variables

While using a config.yaml file is the recommended approach, govee2mqtt also supports configuration via environment variables.

## MQTT Settings

-   `MQTT_HOST` (optional, default = 'localhost')
-   `MQTT_PORT` (optional, default = 1883)
-   `MQTT_USERNAME` (required)
-   `MQTT_PASSWORD` (optional, default = empty password)
-   `MQTT_QOS` (optional, default = 0)
-   `MQTT_PROTOCOL_VERSION` (optional, default = '5') - MQTT protocol version: '3.1.1'/'3' or '5'
-   `MQTT_TLS_ENABLED` (optional) - set to `true` to enable TLS
-   `MQTT_TLS_CA_CERT` (required if using TLS) - path to the CA cert
-   `MQTT_TLS_CERT` (required if using TLS) - path to the private cert
-   `MQTT_TLS_KEY` (required if using TLS) - path to the private key
-   `MQTT_PREFIX` (optional, default = 'govee')
-   `MQTT_DISCOVERY_PREFIX` (optional, default = 'homeassistant')

## Govee Settings

-   `GOVEE_API_KEY` (required) - see https://developer.govee.com/reference/apply-you-govee-api-key
-   `GOVEE_DEVICE_INTERVAL` (optional, default = 30) - polling interval in seconds; estimate 30 sec per 10 devices
-   `GOVEE_DEVICE_BOOST_INTERVAL` (optional, default = 5) - faster polling interval after state changes
-   `GOVEE_LIST_INTERVAL` (optional, default = 300) - how often to refresh the device list

## Other Settings

-   `TZ` (optional) - timezone, e.g. 'America/New_York' (see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List)
-   `DEBUG` (optional) - set to 'True' for verbose logging
