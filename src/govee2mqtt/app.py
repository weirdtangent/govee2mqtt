# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
#!/usr/bin/env python3
import asyncio
import argparse
import logging
from .core import Govee2Mqtt


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="govee2mqtt")
    p.add_argument(
        "-c",
        "--config",
        help="Directory or file path for config.yaml (defaults to /config/config.yaml)",
    )
    return p


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s"
    )
    logging.info("🚀 This is govee2mqtt")

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        with Govee2Mqtt(args=args) as govee2mqtt:
            try:
                asyncio.run(govee2mqtt.main_loop())
            except RuntimeError as e:
                if "asyncio.run() cannot be called from a running event loop" in str(e):
                    # Nested event loop (common in tests or Jupyter) — fall back gracefully
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(govee2mqtt.main_loop())
                else:
                    raise
    except TypeError as e:
        logging.error(f"TypeError: {e}")
    except KeyboardInterrupt:
        logging.warning("Shutdown requested (Ctrl+C). Exiting gracefully...")
    except asyncio.CancelledError:
        logging.warning("Main loop cancelled.")
    except Exception as e:
        logging.exception(f"Unhandled exception in main loop: {e}")
    finally:
        logging.info("govee2mqtt stopped.")
