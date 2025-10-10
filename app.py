# This software is licensed under the MIT License, which allows you to use,
# copy, modify, merge, publish, distribute, and sell copies of the software,
# with the requirement to include the original copyright notice and this
# permission notice in all copies or substantial portions of the software.
#
# The software is provided 'as is', without any warranty.

#!/usr/bin/env python3
import asyncio
import argparse
import logging
from govee_mqtt import GoveeMqtt
from util import load_config

# Parse arguments
argparser = argparse.ArgumentParser()
argparser.add_argument(
    "-c",
    "--config",
    required=False,
    help="Directory or file path for config.yaml (defaults to /config/config.yaml)",
)
args = argparser.parse_args()

# Load configuration
config = load_config(args.config)

# Setup logging
logging.basicConfig(
    format=(
        "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
        if not config["hide_ts"]
        else "[%(levelname)s] %(name)s: %(message)s"
    ),
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG if config["debug"] else logging.INFO,
)

logger = logging.getLogger(__name__)
logger.info(f"Starting govee2mqtt {config['version']}")
logger.info(f"Config loaded from {config['config_from']} ({config['config_path']})")

# Run main loop safely
try:
    with GoveeMqtt(config) as mqtt:
        try:
            # Prefer a clean async run, but handle environments with existing event loops
            asyncio.run(mqtt.main_loop())
        except RuntimeError as e:
            if "asyncio.run() cannot be called from a running event loop" in str(e):
                # Nested event loop (common in tests or Jupyter) — fall back gracefully
                loop = asyncio.get_event_loop()
                loop.run_until_complete(mqtt.main_loop())
            else:
                raise
except KeyboardInterrupt:
    logger.info("Shutdown requested (Ctrl+C). Exiting gracefully...")
except asyncio.CancelledError:
    logger.warning("Main loop cancelled.")
except Exception as e:
    logger.exception(f"Unhandled exception in main loop: {e}")
finally:
    logger.info("govee2mqtt stopped.")
