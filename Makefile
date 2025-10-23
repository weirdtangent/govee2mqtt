.PHONY: image smoke
# Run each recipe in a single shell so heredocs behave nicely
.ONESHELL:

image:
	docker buildx build --no-cache --platform=linux/arm64 --load -t govee2mqtt:dev .

smoke: image
	docker run --rm --entrypoint python -e SERVICE=govee2mqtt -e FORCE_JSON=1 govee2mqtt:dev - <<-'PY'
	from json_logging import setup_logging, get_logger
	setup_logging(); get_logger(__name__).info("smoke", extra={"foo":1})
	PY
