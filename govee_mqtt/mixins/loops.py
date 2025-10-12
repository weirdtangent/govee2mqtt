from .._imports import *

import asyncio
import signal

class LoopsMixin:

    async def device_list_loop(self):
        while self.running:
            await self.refresh_device_list()
            try:
                await asyncio.sleep(self.device_list_interval)
            except asyncio.CancelledError:
                self.logger.debug("device_list_loop cancelled during sleep")
                break

    async def device_loop(self):
        while self.running:
            await self.refresh_all_devices()
            try:
                await asyncio.sleep(self.device_interval)
            except asyncio.CancelledError:
                self.logger.debug("device_loop cancelled during sleep")
                break

    async def device_boosted_loop(self):
        while self.running:
            await self.refresh_boosted_devices()
            try:
                await asyncio.sleep(self.device_boost_interval)
            except asyncio.CancelledError:
                self.logger.debug("device_boost_loop cancelled during sleep")
                break

    # main loop
    async def main_loop(self):
        """Main async runtime loop for Govee2MQTT."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._handle_signal)
            except Exception:
                self.logger.debug(f"Cannot install handler for {sig}")

        self.running = True

        tasks = [
            asyncio.create_task(self.device_list_loop(), name="device_list_loop"),
            asyncio.create_task(self.device_loop(), name="device_loop"),
            asyncio.create_task(self.device_boosted_loop(), name="device_boosted_loop"),
        ]

        try:
            results = await asyncio.gather(*tasks)
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"Task raised exception: {result}", exc_info=True)
                    self.running = False
        except asyncio.CancelledError:
            self.logger.warning("Main loop cancelled — shutting down...")
        except Exception as err:
            self.logger.exception(f"Unhandled exception in main loop: {err}")
            self.running = False
        finally:
            self.logger.info("All loops terminated — cleanup complete.")