# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio


class RefreshMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def refresh_all_devices(self):
        # don't let this kick off until we are done with our list
        while not self.discovery_complete and self.running:
            await asyncio.sleep(1)

        self.logger.info(
            f"Refreshing all devices from Govee (every {self.device_interval} sec)"
        )

        for device_id in self.devices:
            if not self.running:
                break
            if device_id == "service" or device_id in self.boosted:
                continue

            self.refresh_device_states(device_id)

    # refresh boosted devices ---------------------------------------------------------------------

    async def refresh_boosted_devices(self):
        # don't let this kick off until we are done with our list
        while not self.discovery_complete and self.running:
            await asyncio.sleep(1)

        if len(self.boosted) > 0:
            self.logger.info(
                f"Refreshing {len(self.boosted)} boosted devices from Govee"
            )
            for device_id in self.boosted:
                self.boosted.remove(device_id)
                if not self.running:
                    break
                self.refresh_device_states(device_id)
