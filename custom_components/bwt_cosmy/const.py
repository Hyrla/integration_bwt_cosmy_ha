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