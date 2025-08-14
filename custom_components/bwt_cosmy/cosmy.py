# BLE logic for Cosmy device, refactored for Home Assistant integration

import logging
from typing import Optional, Tuple, Any

WRITE_CHAR_UUID  = "0000fff3-0000-1000-8000-00805f9b34fb"
STATUS_CHAR_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"

CMD_QUERY_STATUS = bytes.fromhex("ffa50a020406ba")
CMD_POWER_ON     = bytes.fromhex("ffa50a020101b2")
CMD_POWER_OFF    = bytes.fromhex("ffa50a020100b1")

_LOGGER = logging.getLogger(__name__)

def parse_state_and_minutes(p: bytes) -> Tuple[Optional[bool], Optional[int]]:
    """
    Parses 20-byte notifications (0xFFF4) starting with ffa53a1384...
    - State: bit 7 of p[5] (1=ON)
    - Remaining minutes: uint16 LE at p[6:8] if ON, otherwise 0
    """
    if len(p) == 20 and p.startswith(bytes.fromhex("ffa53a1384")):
        is_on = bool(p[5] & 0x80)
        if is_on:
            mins = int.from_bytes(p[6:8], "little")
        else:
            mins = 0
        return is_on, mins
    return None, None


# Nouvelle version pour Home Assistant Bluetooth API
class CosmyClient:
    def __init__(self, ble_client: Any):
        self.ble_client = ble_client

    async def power_on(self):
        _LOGGER.debug("Sending POWER ON command via Home Assistant BLE client")
        await self._write(CMD_POWER_ON)

    async def power_off(self):
        _LOGGER.debug("Sending POWER OFF command via Home Assistant BLE client")
        await self._write(CMD_POWER_OFF)

    async def query_status(self, wait_s: float = 2.0) -> Tuple[Optional[bool], Optional[int]]:
        last = None

        def on_notify(_h, data: bytearray):
            nonlocal last
            b = bytes(data)
            state, mins = parse_state_and_minutes(b)
            _LOGGER.debug(f"[NOTIFY] {b.hex()}  "
                         f"{'(ON)' if state else '(OFF)' if state is False else ''} "
                         f"{'' if mins is None else f'({mins} min)'}")
            if state is not None or mins is not None:
                last = (state, mins)

        c = self.ble_client
        await c.start_notify(STATUS_CHAR_UUID, on_notify)
        await c.write_gatt_char(WRITE_CHAR_UUID, CMD_QUERY_STATUS, response=True)
        import asyncio
        await asyncio.sleep(wait_s)
        try:
            await c.stop_notify(STATUS_CHAR_UUID)
        except Exception:
            pass
        return last

    async def _write(self, payload: bytes):
        c = self.ble_client
        await c.write_gatt_char(WRITE_CHAR_UUID, payload, response=True)

# Example usage in Home Assistant:
#
# from .cosmy import CosmyClient
# client = CosmyClient(address="XX:XX:XX:XX:XX:XX")
# await client.power_on()
# state, mins = await client.query_status()
