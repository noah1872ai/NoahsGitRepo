# =============================================================================
# bridge.py  —  HAL Modbus TCP → MQTT bridge
#
# Polls Arduino over Modbus TCP and bridges to HiveMQ cloud via MQTT.
# Uses WebSockets on port 443 to bypass corporate firewall restrictions.
#
# INSTALL DEPENDENCIES:
#   uv pip install pymodbus "paho-mqtt[websockets]"
#
# USAGE:
#   uv run bridge.py
# =============================================================================

import time
import logging
import paho.mqtt.client as mqtt
from pymodbus.client import ModbusTcpClient

# =============================================================================
# CONFIG
# =============================================================================

ARDUINO_IP     = "192.168.1.100"
ARDUINO_PORT   = 502
MODBUS_UNIT_ID = 1

MQTT_BROKER    = "a91e0f8a35d1461e9629854783787c17.s1.eu.hivemq.cloud"
MQTT_PORT      = 443                # WebSockets over TLS — bypasses port 8883 firewall
MQTT_USERNAME  = "your_username"    # ← update
MQTT_PASSWORD  = "your_password"    # ← update

POLL_INTERVAL  = 0.25               # seconds between Modbus polls

# MQTT topics
TOPIC_BASE          = "1872/demo/arduino"
TOPIC_LED_ENABLE    = f"{TOPIC_BASE}/led_enable"
TOPIC_BLINK_RATE    = f"{TOPIC_BASE}/blink_rate"
TOPIC_LED_STATE     = f"{TOPIC_BASE}/led_state"
TOPIC_HEARTBEAT     = f"{TOPIC_BASE}/heartbeat"
TOPIC_BRIDGE_STATUS = f"{TOPIC_BASE}/bridge_status"

# Modbus register indices (0-based, matching Arduino sketch)
REG_LED_ENABLE = 0   # Holding — 400001
REG_BLINK_RATE = 1   # Holding — 400002
REG_LED_STATE  = 0   # Input   — 300001
REG_HEARTBEAT  = 1   # Input   — 300002

# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# =============================================================================
# MQTT callbacks
# =============================================================================

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info(f"MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
        client.publish(TOPIC_BRIDGE_STATUS, "online", retain=True)
        client.subscribe(TOPIC_LED_ENABLE)
        client.subscribe(TOPIC_BLINK_RATE)
        log.info(f"Subscribed to {TOPIC_LED_ENABLE}")
        log.info(f"Subscribed to {TOPIC_BLINK_RATE}")
    else:
        log.error(f"MQTT connection failed, rc={rc}")

def on_disconnect(client, userdata, rc):
    log.warning("MQTT disconnected")

def on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode().strip()
    log.info(f"MQTT RX  {topic} = {payload}")

    try:
        value = int(payload)
    except ValueError:
        log.warning(f"Non-integer payload ignored: {payload}")
        return

    modbus = userdata["modbus"]
    if not modbus.is_socket_open():
        log.warning("Modbus not connected — skipping write")
        return

    if topic == TOPIC_LED_ENABLE:
        value = max(0, min(2, value))
        modbus.write_register(REG_LED_ENABLE, value, slave=MODBUS_UNIT_ID)
        log.info(f"Modbus TX  LED_Enable = {value}")

    elif topic == TOPIC_BLINK_RATE:
        value = max(1, min(100, value))
        modbus.write_register(REG_BLINK_RATE, value, slave=MODBUS_UNIT_ID)
        log.info(f"Modbus TX  Blink_Rate = {value}")

# =============================================================================
# Main loop
# =============================================================================

def main():
    # Connect to Arduino via Modbus TCP
    modbus = ModbusTcpClient(ARDUINO_IP, port=ARDUINO_PORT)
    if not modbus.connect():
        log.error(f"Could not connect to Arduino at {ARDUINO_IP}:{ARDUINO_PORT}")
        return
    log.info(f"Modbus TCP connected to {ARDUINO_IP}:{ARDUINO_PORT}")

    # Connect to HiveMQ via MQTT over WebSockets + TLS on port 443
    client = mqtt.Client(
        transport="websockets",
        userdata={"modbus": modbus}
    )
    client.ws_set_options(path="/mqtt")
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.will_set(TOPIC_BRIDGE_STATUS, "offline", retain=True)
    client.tls_set()

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    log.info("Bridge running — polling Arduino every 250ms")
    log.info(f"Topics: {TOPIC_BASE}/#")

    try:
        while True:
            if not modbus.is_socket_open():
                log.warning("Modbus connection lost — reconnecting...")
                modbus.connect()

            result = modbus.read_input_registers(
                address=REG_LED_STATE,
                count=2,
                slave=MODBUS_UNIT_ID
            )

            if not result.isError():
                led_state = result.registers[REG_LED_STATE]
                heartbeat = result.registers[REG_HEARTBEAT]
                client.publish(TOPIC_LED_STATE, str(led_state))
                client.publish(TOPIC_HEARTBEAT, str(heartbeat))
                log.info(f"Modbus RX  LED_State={led_state}  Heartbeat={heartbeat}")
            else:
                log.warning(f"Modbus read error: {result}")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Bridge stopped")
    finally:
        client.publish(TOPIC_BRIDGE_STATUS, "offline", retain=True)
        client.loop_stop()
        client.disconnect()
        modbus.close()

if __name__ == "__main__":
    main()
