# weirdtangent/govee2mqtt

Expose multiple Govee devices and events to an MQTT broker, primarily designed to work with Home Assistant.
Forked from [dlashua/govee2mqtt](https://github.com/dlashua/govee2mqtt)

A few notes:
* Govee's API is SLOW. Not only does each request take longer than it should, it takes, sometimes, 3 to 4 seconds for the command to reach the light strip.
* If you have many (10+) Govee devices, you will need to raise the GOVEE_DEVICE_INTERVAL setting because of their daily limit of API requests (currently 10,000/day).
  Budget it as `devices x (86400 / GOVEE_DEVICE_INTERVAL)` for the polling loop, plus `86400 / GOVEE_LIST_INTERVAL` for the device list itself, plus one call per *sensor* per rescan (a sensor's readings are checked before it is adopted), plus one call per command you send.
  The `GOVEE_DEVICE_INTERVAL` default of 30 only suits a handful of devices - 28 devices would spend 80,640 calls/day on state polls alone, and even at 180 seconds it is 13,440. Around 360 seconds is what 28 devices need to stay comfortably inside the quota.
* Support is there for power on/off, brightness, and rgb_color.
* "Rediscover" button added to service - when pressed, device discovery is re-run so HA will rediscover deleted devices
* Device groups created in the Govee app are adopted as on/off-only lights (`light.<name>_group`), but they cannot report their own state - see [Device Groups Are Write-Only](#device-groups-are-write-only)

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

### Device Groups Are Write-Only

Groups you create in the Govee app (`BaseGroup` / `SameModeGroup`) show up in the device list, but
`/device/state` and `/device/scenes` both reject them with `devices not exist`. They are adopted as
on/off-only lights, and because there is no state to read, govee2mqtt never polls them — the entity
reflects the last command it sent, not what the group is really doing. Change a group from the Govee
app or turn off one of its members and Home Assistant will not notice.

The API also under-reports groups in two ways. It never says what is *in* one — the payload is a
name and `powerSwitch`, which would look identical for a group of humidifiers — so the light domain
is an assumption. And it advertises only `powerSwitch` even where the Govee app can clearly do more:
a **Same Model** group (all members identical) offers the full capability set in the app, and a
**General Group** (mixed members, e.g. "Bedroom Red") offers on/off, colour, brightness and scenes.
Neither shows up in the API, and whether `/device/control` would accept them anyway is untested.

Group entities are named for what they are — `light.great_room_lamps_group` rather than
`light.great_room_lamps_light` —
both because it reads better and because a group sharing a name with a real device would otherwise
contest its `entity_id` and be handed a `_2` suffix permanently.

### Bluetooth-Only Sensors Are Invisible

A sensor with no WiFi path (an H5074, for instance, with no Govee gateway) is listed by
`/user/devices` but answers `online: false` with an empty string for every reading, so the cloud
API can see that it exists and never what it says. govee2mqtt does not adopt a sensor that reports
nothing — entities that can never hold a value are worse than no entities, and polling them costs
API quota to keep learning nothing. If such a sensor later gains a gateway it is adopted on the
next rescan. Home Assistant's own Govee BLE integration reads these directly over Bluetooth.

### Incorrect Device Capabilities

The API sometimes reports incorrect capabilities for devices. For example, the H6042 Smart TV Light Bar reports MusicMode options that don't actually work when sent back to the API, while the mobile app offers completely different (working) options.

## Out of Scope

### Non-Docker Environments

Docker is the only supported way of deploying the application. The app should run directly via Python but this is not supported.

## See also
* [amcrest2mqtt](https://github.com/weirdtangent/amcrest2mqtt)
* [blink2mqtt](https://github.com/weirdtangent/blink2mqtt)

## Contributors

* [@dlashua](https://github.com/dlashua) — original project author
* [@weirdtangent](https://github.com/weirdtangent) — fork maintainer
* [@andrzejmarszalekam-ai](https://github.com/andrzejmarszalekam-ai) — fixed stale light color mode state (#75)

### Buy Me A Coffee

A few people have kindly requested a way to donate a small amount of money. If you feel so inclined I've set up a "Buy Me A Coffee" page where you can donate a small sum. Please do not feel obligated to donate in any way - I work on the app because it's useful to myself and others, not for any financial gain - but any token of appreciation is much appreciated 🙂

<a href="https://buymeacoffee.com/weirdtangent">Buy Me A Coffee</a>

---

### Build & Quality Status

![Build & Release](https://img.shields.io/github/actions/workflow/status/weirdtangent/govee2mqtt/deploy.yaml?branch=main&label=build%20%26%20release&logo=githubactions)
![Lint](https://img.shields.io/github/actions/workflow/status/weirdtangent/govee2mqtt/deploy.yaml?branch=main&label=lint%20(ruff%2Fmypy)&logo=python)
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

## Entity IDs and the `unique_id` contract

Home Assistant assigns an `entity_id` **once**, at first discovery, and keys its registry on
`unique_id`. It never reassigns that `entity_id` afterwards — not when the entity is renamed, and
not when discovery is cleared and republished. This was verified directly: clearing the retained
discovery topic, waiting 25 seconds, and republishing restores the *identical* `entity_id`.

Two rules follow, and breaking either one strands an entity permanently:

1. **Never reuse a `unique_id` for a different entity.** If a component's meaning changes, mint a
   new `unique_id` deliberately.
2. **Every component publishes an explicit `def_ent_id`**, derived from its stable component key
   rather than its display name. Without it HA derives the `entity_id` from the display name, so
   renaming a component in a later release leaves its `entity_id` describing the old name — and a
   differently-named component can end up owning it.

   This option used to be `obj_id` (`object_id`). **HA Core 2026.4 removed it**, after deprecating
   it in 2025.10; it is not aliased, so a payload still publishing `obj_id` silently loses control
   of its `entity_id`s. The replacement, `default_entity_id`/`def_ent_id`, takes a *full*
   `entity_id` (`light.great_room_lamps_light`) rather than a bare slug. `mqtt_helper.obj_id()`
   still computes the slug; `mqtt_helper.apply_default_entity_ids()` pairs it with each component's
   domain at publish time.

### If an entity_id is already wrong

It cannot be fixed from this service, because no MQTT message can reassign an `entity_id`. Rename
it in Home Assistant under **Settings → Devices & Services → Entities**. If two entities have
swapped ids, rename the squatter first to free the id, then rename the correct entity into it.

The **Reset discovery** button clears and republishes retained discovery and sweeps orphaned
configs for devices that no longer exist. It does *not* reassign `entity_id`s.
