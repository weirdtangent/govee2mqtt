# weirdtangent/govee2mqtt

Expose multiple Govee devices and events to an MQTT broker, primarily designed to work with Home Assistant.
Forked from [dlashua/govee2mqtt](https://github.com/dlashua/govee2mqtt)

A few notes:
* Govee's API is SLOW. Not only does each request take longer than it should, it takes, sometimes, 3 to 4 seconds for the command to reach the light strip.
* If you have many (10+) Govee devices, you will need to raise the GOVEE_DEVICE_INTERVAL setting because of their daily limit of API requests (currently 10,000/day).
* Support is there for power on/off, brightness, and rgb_color.
* "Rediscover" button added to service - when pressed, device discovery is re-run so HA will rediscover deleted devices

## Docker

For `docker-compose`, use the [configuration included](https://github.com/weirdtangent/govee2mqtt/blob/master/docker-compose.yaml) in this repository.

Using the [docker image](https://hub.docker.com/repository/docker/graystorm/govee2mqtt/general), mount your configuration volume at `/config` and include a `config.yaml` file (see the included [config.yaml.sample](config.yaml.sample) file as a template).

## Configuration

The recommended way to configure govee2mqtt is via the `config.yaml` file. See [config.yaml.sample](config.yaml.sample) for a complete example with all available options.

### MQTT Settings

```yaml
mqtt:
  host: 10.10.10.1
  port: 1883
  username: mqtt
  password: password
  qos: 0
  protocol_version: "5"  # MQTT protocol version: 3.1.1/3 or 5
  prefix: govee
  discovery_prefix: homeassistant
  # TLS settings (optional)
  tls_enabled: false
  tls_ca_cert: filename
  tls_cert: filename
  tls_key: filename
```

### Govee Settings

```yaml
govee:
  api_key: xxxxx-xxx-xxxxxx  # see https://developer.govee.com/reference/apply-you-govee-api-key
  device_interval: 30        # polling interval; estimate 30 sec per 10 devices due to API rate limits
  device_boost_interval: 2   # faster polling after state changes
  device_list_interval: 300  # how often to refresh device list
```

### Other Settings

```yaml
timezone: America/New_York   # see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
```

### Environment Variables

While the config file is recommended, environment variables are also supported. See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for the full list of available environment variables.

## Govee API Limitations

The Govee API has significant limitations that affect what this integration can do. These are **not bugs in govee2mqtt** - they are limitations of the Govee API itself. See the [Govee API documentation](https://developer.govee.com/) for reference.

### State Not Reported

The Govee API does not report the current state of these settings, so govee2mqtt cannot know their initial state on startup:

- **DreamView mode** - on/off state is never reported
- **MusicMode** - active mode is never reported
- **NightLight mode** - on/off state is never reported
- **Gradient mode** - on/off state is never reported

### Inconsistent Mode Behavior

- When enabling one mode, Govee does not report that other mutually-exclusive modes are now disabled
- There is no documented way to turn MusicMode OFF (setting a solid color is a workaround)
- Enabling DreamView while the light is OFF will turn the light ON automatically, but enabling Gradient while OFF leaves the light OFF

### Incorrect Device Capabilities

The API sometimes reports incorrect capabilities for devices. For example, the H6042 Smart TV Light Bar reports MusicMode options that don't actually work when sent back to the API, while the mobile app offers completely different (working) options.

## Out of Scope

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
