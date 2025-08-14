#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
This script was created for proof of concept purposes. It is not meant for production use.
"""

import argparse, asyncio
from typing import Optional
from bleak import BleakClient

WRITE_CHAR_UUID  = "0000fff3-0000-1000-8000-00805f9b34fb"
STATUS_CHAR_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"

CMD_QUERY_STATUS = bytes.fromhex("ffa50a020406ba")
CMD_POWER_ON     = bytes.fromhex("ffa50a020101b2")
CMD_POWER_OFF    = bytes.fromhex("ffa50a020100b1")

def parse_state_and_minutes(p: bytes) -> tuple[Optional[bool], Optional[int]]:
    """
    Parse les notifs 20 octets (0xFFF4) qui commencent par ffa53a1384...
    - Etat: bit7 de p[5] (1=ON)
    - Minutes restantes: uint16 LE à p[6:8] si ON, sinon 0
    """
    if len(p) == 20 and p.startswith(bytes.fromhex("ffa53a1384")):
        is_on = bool(p[5] & 0x80)
        if is_on:
            mins = int.from_bytes(p[6:8], "little")
        else:
            mins = 0
        return is_on, mins
    return None, None

async def write(addr: str, payload_hex: str, timeout: float):
    data = bytes.fromhex(payload_hex)
    async with BleakClient(addr, timeout=timeout) as c:
        await c.write_gatt_char(WRITE_CHAR_UUID, data, response=True)

async def query_status(addr: str, timeout: float, wait_s: float = 2.0):
    last = None
    async with BleakClient(addr, timeout=timeout) as c:
        # s'abonner à 0xFFF4
        def on_notify(_h, data: bytearray):
            nonlocal last
            b = bytes(data)
            state, mins = parse_state_and_minutes(b)
            print(f"[NOTIFY] {b.hex()}  "
                  f"{'(ON)' if state else '(OFF)' if state is False else ''} "
                  f"{'' if mins is None else f'({mins} min)'}")
            if state is not None or mins is not None:
                last = (state, mins)

        await c.start_notify(STATUS_CHAR_UUID, on_notify)
        # déclenche la réponse d'état
        await c.write_gatt_char(WRITE_CHAR_UUID, CMD_QUERY_STATUS, response=True)
        await asyncio.sleep(wait_s)
        try: await c.stop_notify(STATUS_CHAR_UUID)
        except Exception: pass

    return last  # (state: bool|None, minutes: int|None)

async def main():
    ap = argparse.ArgumentParser(description="RoboCleaner BLE (état & temps restant)")
    ap.add_argument("--addr", required=True)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--status", action="store_true", help="Afficher ON/OFF + minutes")
    ap.add_argument("--on", action="store_true")
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--wait", type=float, default=2.0)
    args = ap.parse_args()

    if args.on and args.off:
        raise SystemExit("Choisis --on ou --off, pas les deux.")
    if args.on:
        await write(args.addr, CMD_POWER_ON.hex(), args.timeout); return
    if args.off:
        await write(args.addr, CMD_POWER_OFF.hex(), args.timeout); return

    # défaut: --status
    state, mins = await query_status(args.addr, args.timeout, args.wait)
    if state is None and mins is None:
        print("RESULT=UNKNOWN")
    else:
        s = "ON" if state else "OFF" if state is False else "UNKNOWN"
        m = "" if mins is None else f" {mins}min"
        print(f"RESULT={s}{m}")

if __name__ == "__main__":
    asyncio.run(main())
