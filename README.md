
Forked 2025-02-04 from [dlashua/govee2mqtt](https://github.com/weirdtangent/govee2mqtt)

A few notes:
* Govee's API is SLOW. Not only does each request take longer than it should, it takes, sometimes, 3 to 4 seconds for the command to reach the light strip.
* If you have many (10+) Govee devices, you will need to raise the GOVEE_DEVICE_INTERVAL setting because of their daily limit of API requests.
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

An docker image is available at `weirdtangent/govee2mqtt:latest`. You can mount your configuration volume at `/config` or use the ENV variables.


# Getting an API KEY
* Open the Govee App
* Tap on the "profile" icon (bottom right)
* Tap on "about us"
* Tap on "Apply for API Key"
* Get the API key via email within minutes
