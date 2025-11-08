# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Jeff Culverhouse
import asyncio

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from govee2mqtt.interface import GoveeServiceProtocol as Govee2Mqtt


class RefreshMixin:
    async def refresh_all_devices(self: Govee2Mqtt) -> None:
        # don't let this kick off until we are done with our list
        while not self.discovery_complete and self.running:
            await asyncio.sleep(1)

        self.logger.info(f"Refreshing all devices from Govee (every {self.device_interval} sec)")

        tasks = [self.refresh_device_states(device_id) for device_id in self.devices if device_id not in self.boosted]
        await asyncio.gather(*tasks)

    # refresh boosted devices ---------------------------------------------------------------------

    async def refresh_boosted_devices(self: Govee2Mqtt) -> None:
        # don't let this kick off until we are done with our list
        while not self.discovery_complete and self.running:
            await asyncio.sleep(1)

        if len(self.boosted) > 0:
            self.logger.info(f"Refreshing {len(self.boosted)} boosted devices from Govee")

            tasks = []
            for device_id in self.boosted:
                self.boosted.remove(device_id)
                tasks.append(self.refresh_device_states(device_id))

            await asyncio.gather(*tasks)
