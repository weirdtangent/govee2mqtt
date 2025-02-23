# weirdtangent/govee2mqtt

Forked from [dlashua/govee2mqtt](https://github.com/dlashua/govee2mqtt)

A few notes:
* Govee's API is SLOW. Not only does each request take longer than it should, it takes, sometimes, 3 to 4 seconds for the command to reach the light strip.
* If you have many (10+) Govee devices, you will need to raise the GOVEE_DEVICE_INTERVAL setting because of their daily limit of API requests (currently 10,000/day)
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

An docker image is available at `weirdtangent/govee2mqtt:latest`. You can mount your configuration volume at `/config` (and see the
included `config.yaml.sample` file) or use the ENV variables:

It supports the following environment variables:

-   `MQTT_HOST: 10.10.10.1`
-   `MQTT_USERNAME: admin`
-   `MQTT_PASSWORD: password`
-   `MQTT_PREFIX: govee`
-   `MQTT_HOMEASSISTANT: homeassistant`
-   `GOVEE_API_KEY: [your_api_key]` (https://developer.govee.com/reference/apply-you-govee-api-key)
-   `GOVEE_DEVICE_INTERVAL: 30` (higher if 10+ Govee devices)
-   `GOVEE_DEVICE_BOOST_INTERVAL: 5`
-   `GOVEE_LIST_INTERVAL: 300`

## Out of Scope

### Non-Docker Environments

Docker is the only supported way of deploying the application. The app should run directly via Python but this is not supported.

### Buy Me A Coffee

A few people have kindly requested a way to donate a small amount of money. If you feel so inclined I've set up a "Buy Me A Coffee"
page where you can donate a small sum. Please do not feel obligated to donate in any way - I work on the app because it's
useful to myself and others, not for any financial gain - but any token of appreciation is much appreciated 🙂

<a href="https://buymeacoffee.com/weirdtangent">Buy Me A Coffee</a>
