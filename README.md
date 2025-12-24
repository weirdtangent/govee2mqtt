# weirdtangent/govee2mqtt

Expose multiple Govee devices and events to an MQTT broker, primarily designed to work with Home Assistant.
Forked from [dlashua/govee2mqtt](https://github.com/dlashua/govee2mqtt)

A few notes:
* Govee's API is SLOW. Not only does each request take longer than it should, it takes, sometimes, 3 to 4 seconds for the command to reach the light strip.
* If you have many (10+) Govee devices, you will need to raise the GOVEE_DEVICE_INTERVAL setting because of their daily limit of API requests (currently 10,000/day).
* Support is there for power on/off, brightness, and rgb_color.
* "Rediscover" button added to service - when pressed, device discovery is re-run so HA will rediscover deleted devices

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

An docker image is available at `graystorm/govee2mqtt:latest`. You can mount your configuration volume at `/config` (and see the included `config.yaml.sample` file) or use the ENV variables:

It supports the following environment variables:

-   `MQTT_HOST: 10.10.10.1`
-   `MQTT_USERNAME: admin`
-   `MQTT_PASSWORD: password`
-   `MQTT_PREFIX: govee`
-   `MQTT_DISCOVERY_PREFIX: homeassistant`

-   `GOVEE_API_KEY: [your_api_key]` (see https://developer.govee.com/reference/apply-you-govee-api-key)
-   `GOVEE_DEVICE_INTERVAL: 30` (estimate 30 sec per 10 Govee devices, so set to 60 if you have 10-20 devices, etc)
-   `GOVEE_DEVICE_BOOST_INTERVAL: 5`
-   `GOVEE_LIST_INTERVAL: 300`

-   `TZ: America/New_York` (see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List)
-   `DEBUG: True` (for much more logging)

# Unsupported so far by Govee, or just plain wrong

A few fancy options are only half-supported by Govee:

## MusicMode

I am trying to figure out if there's any way to make this more automatic or easier.

In HomeAssistant, if you create a `Helper` like this:

> Note: you can see what MusicMode options your particular light supports by looking at the `MusicMode` property on the MQTT device and click on `Attributes` to see the `Possible States` - and you can skip any modes you don't like or never use

```yaml
input_select:
  office_light_music_mode:
    options:
      - Off
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
      retain: false
      topic: homeassistant/device/govee-XXXXXXXXXXXXXXXX/set/music_mode
      payload: "{{ states('input_select.office_light_music_mode') }}"
mode: single
```

You can add that pulldown input to a dashboard, and select a MusicMode and have the command sent to MQTT which will send it to Govee.

HOWEVER: Govee does not report back the state of this or NightLight mode or Gradient Mode or others. Also, they are sometimes just plain wrong. For example, they claim my `H6042 Smart TV Light Bar` does MusicModes of:

```json
"options":[
  {"name": "Energic", "value": 5},
  {"name": "Rhythm", "value": 3},
  {"name": "Spectrum", "value": 6},
  {"name": "Rolling", "value": 4}
]
```

But sending those values back Govee makes no change to the Light Bar. Sending other values just fails with a `Parameter value out of range` error. Yet, in my app, it lets me set `Vivid`, `Rhythm`, `Bouncing Ball`, `Luminous`, `Beat`, `Torch`, `Rainbow Circle`, and `Shiny`.

Also, when turning one mode OFF, Govee will respond that the mode was supposedly turned ON, but does not update that others are now OFF. For example, if `Dreamview` mode is ON, and you turn ON `Gradient` mode, they don't update you that `Dreamview` mode is now OFF. In fact, there doesn't seem to be a documented way of turning `MusicMode` OFF. You can force a solid color. Turning the light OFF and back ON doesn't do it.

Another example, turning the light OFF and then turning on `Dreamview` mode will turn the light ON automatically. But turning on `Gradient` mode will not - the light stays OFF. If you then turn the light ON, it will be in `Gradient` mode.

All of this makes it almost worthless to do much with this Govee API - the very basic functions work, but everything fancy is a toss-up :(

## Out of Scope

### Working around Govee API Problems

There just isn't much hope. I don't want to even want to attempt the multi-cast LAN option for fear that it works just as poorly and will be as big of a waste of time. I really hope they come out with a v2 of their API and fix all of this. I had high hopes because their Android app is so feature-full. The docs I am going by are <a href="https://developer.govee.com/">here</a> as of March 2025.

### Non-Docker Environments

Docker is the only supported way of deploying the application. The app should run directly via Python but this is not supported.

## See also
* [amcrest2mqtt](https://github.com/weirdtangent/amcrest2mqtt)
* [blink2mqtt](https://github.com/weirdtangent/blink2mqtt)

### Buy Me A Coffee

A few people have kindly requested a way to donate a small amount of money. If you feel so inclined I've set up a "Buy Me A Coffee" page where you can donate a small sum. Please do not feel obligated to donate in any way - I work on the app because it's useful to myself and others, not for any financial gain - but any token of appreciation is much appreciated 🙂

<a href="https://buymeacoffee.com/weirdtangent">Buy Me A Coffee</a>

---

### Build & Quality Status

![Build & Release](https://img.shields.io/github/actions/workflow/status/weirdtangent/govee2mqtt/deploy.yaml?branch=main&label=build%20%26%20release&logo=githubactions)
![Lint](https://img.shields.io/github/actions/workflow/status/weirdtangent/govee2mqtt/deploy.yaml?branch=main&label=lint%20(ruff%2Fblack%2Fmypy)&logo=python)
![Docker Build](https://img.shields.io/github/actions/workflow/status/weirdtangent/govee2mqtt/deploy.yaml?branch=main&label=docker%20build&logo=docker)
![Python](https://img.shields.io/badge/python-3.12%20|%203.13%20|%203.14-blue?logo=python)
![Release](https://img.shields.io/github/v/release/weirdtangent/govee2mqtt?sort=semver)
![Docker Image Tag](https://img.shields.io/github/v/release/weirdtangent/govee2mqtt?label=docker%20tag&sort=semver&logo=docker)
![Docker Pulls](https://img.shields.io/docker/pulls/graystorm/govee2mqtt?logo=docker)
![License](https://img.shields.io/github/license/weirdtangent/govee2mqtt)

### Security

![Trivy Scan](https://img.shields.io/github/actions/workflow/status/weirdtangent/govee2mqtt/deploy.yaml?branch=main&label=trivy%20scan&logo=aquasecurity)
![Cosign](https://img.shields.io/badge/cosign-signed-blue?logo=sigstore)
![SBOM](https://img.shields.io/badge/SBOM-included-green)
![Provenance](https://img.shields.io/badge/provenance-attested-green)
