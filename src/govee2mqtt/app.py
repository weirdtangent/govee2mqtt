# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
#!/usr/bin/env python3
import asyncio
import argparse
from json_logging import setup_logging, get_logger
from .core import Govee2Mqtt


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="govee2mqtt", exit_on_error=True)
    p.add_argument(
        "-c",
        "--config",
        help="Directory or file path for config.yaml (defaults to /config/config.yaml)",
    )
    return p

def main(argv=None):
    setup_logging()
    logger = get_logger(__name__)

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
        logger.error(f"TypeError: {e}")
    except ValueError:
        pass
    except KeyboardInterrupt:
        logger.warning("Shutdown requested (Ctrl+C). Exiting gracefully...")
    except asyncio.CancelledError:
        logger.warning("Main loop cancelled.")
    except Exception as e:
        logger.exception(f"Unhandled exception in main loop: {e}")
    finally:
        logger.info("govee2mqtt stopped.")
