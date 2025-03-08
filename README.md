# weirdtangent/govee2mqtt

Expose multiple Govee devices and events to an MQTT broker, primarily designed to work with Home Assistant. A WIP, since I'm new to Python.

Forked from [dlashua/govee2mqtt](https://github.com/dlashua/govee2mqtt)

A few notes:
* Govee's API is SLOW. Not only does each request take longer than it should, it takes, sometimes, 3 to 4 seconds for the command to reach the light strip.
* If you have many (10+) Govee devices, you will need to raise the GOVEE_DEVICE_INTERVAL setting because of their daily limit of API requests (currently 10,000/day).
* Support is there for power on/off, brightness, and rgb_color.

# Getting Started
## Direct Install
```bash
git clone https://github.com/weirdtangent/govee2mqtt.git
cd govee2mqtt
pip3 install -r ./requirements.txt
cp config.yaml.sample config.yaml
vi config.yaml
python3 ./app.py -c ./
```

## Docker
For `docker-compose`, use the [configuration included](https://github.com/weirdtangent/govee2mqtt/blob/master/docker-compose.yaml) in this repository.

An docker image is available at `weirdtangent/govee2mqtt:latest`. You can mount your configuration volume at `/config` (and see the included `config.yaml.sample` file) or use the ENV variables:

It supports the following environment variables:

-   `MQTT_HOST: 10.10.10.1`
-   `MQTT_USERNAME: admin`
-   `MQTT_PASSWORD: password`
-   `MQTT_PREFIX: govee`
-   `MQTT_HOMEASSISTANT: true` (with False, it won't publish HA discovery devices)
-   `MQTT_DISCOVERY_PREFIX: homeassistant`

-   `GOVEE_API_KEY: [your_api_key]` (see https://developer.govee.com/reference/apply-you-govee-api-key)
-   `GOVEE_DEVICE_INTERVAL: 30` (estimate 30 sec per 10 Govee devices, so set to 60 if you have 10-20 devices, etc)
-   `GOVEE_DEVICE_BOOST_INTERVAL: 5`
-   `GOVEE_LIST_INTERVAL: 300`

-   `TZ: America/New_York` (see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List)
-   `HIDE_TS: False` (hide timestamps in logs, in case your log-viewer adds one already)
-   `DEBUG: True` (for much more logging)

# Unsupported so far by Govee, but...

A few fancy options are only half-supported by Govee:

## MusicMode

I am trying to figure out if there's any way to make this more automatic or easier.

In HomeAssistant, if you create a `Helper` like this:

> Note: you can see what MusicMode options your particular light supports by looking at the `MusicMode` property on the MQTT device and click on `Attributes` to see the `Possible States` - and you can skip any modes you don't like or never use

```yaml
input_select:
  office_light_music_mode:
    options:
      - Unknown
      - Energic
      - Dynamic
      - Calm
      - ...
    editable: true
    icon: mdi:dance-ballroom
    friendly_name: Set Office Light MusicMode
```

and then an `Automation` like:

```yaml
alias: Set Office Light MusicMode
description: ""
triggers:
  - trigger: state
    entity_id:
      - input_select.office_light_music_mode
conditions:
  - condition: template
    value_template: >-
      {% if states.input_select.office_light_music_mode.state !=
      states.sensor.office_light_music_mode.state %} true {% else %} False {%
      endif %}
actions:
  - action: mqtt.publish
    metadata: {}
    data:
      evaluate_payload: false
      qos: "0"
      retain: true
      topic: homeassistant/device/govee-XXXXXXXXXXXXXXXX/set/music_mode
      payload: "{{ states('input_select.office_light_music_mode') }}"
mode: single
```

You can add that pulldown input to a dashboard, and select a MusicMode and have the command sent to MQTT which will send it to Govee.

## Others to come...


## Out of Scope

### Non-Docker Environments

Docker is the only supported way of deploying the application. The app should run directly via Python but this is not supported.

### Buy Me A Coffee

A few people have kindly requested a way to donate a small amount of money. If you feel so inclined I've set up a "Buy Me A Coffee" page where you can donate a small sum. Please do not feel obligated to donate in any way - I work on the app because it's useful to myself and others, not for any financial gain - but any token of appreciation is much appreciated 🙂

<a href="https://buymeacoffee.com/weirdtangent">Buy Me A Coffee</a>

### How Happy am I?

<img src="https://github.com/weirdtangent/govee2mqtt/actions/workflows/deploy.yaml/badge.svg" />
