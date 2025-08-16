DOMAIN = "bwt_cosmy"

# GATT UUIDs
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_WRITE   = "0000fff3-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY  = "0000fff4-0000-1000-8000-00805f9b34fb"

# Commands
CMD_ON   = bytes.fromhex("ffa50a020101b2")
CMD_OFF  = bytes.fromhex("ffa50a020100b1")
CMD_STAT = bytes.fromhex("ffa50a020406ba")

CONF_ADDRESS = "address"
CONF_NAME = "name"

# Shared data key
DATA_COORDINATOR = "coordinator"

# Dispatcher signal names (per-device)
SIGNAL_STATE_FMT   = "bwt_cosmy_{addr}_state"    # payload: bool (cleaning) + minutes
SIGNAL_MINUTES_FMT = "bwt_cosmy_{addr}_minutes"  # payload: int
SIGNAL_IN_WATER_FMT = "bwt_cosmy_{addr}_in_water"  # payload: bool (in water)
SIGNAL_REFRESH_FMT = "bwt_cosmy_{addr}_refresh"  # sensor can request a refresh