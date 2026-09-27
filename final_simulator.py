import argparse
import copy
import json
import random
import signal
import time
import os
import threading
import sys
from datetime import datetime, timezone
from pathlib import Path
import msvcrt
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTT_ERR_SUCCESS

RUNNING = True
CURRENT_MODE = "summer"


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def perturb(value, amount, minimum=None, maximum=None):
    value += random.uniform(-amount, amount)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def simulate(state, elapsed, timers, mode):
    """
    Simulates physical variables grounded in SCAR READER and MET READER
    continental datasets (e.g., RACMO2, MAR, and AWS station data).
    """
    environment = state["environment"]
    internal = state["internal_conditions"]
    energy = state["energy"]
    state["timestamp"] = utc_timestamp()

    external_temperature = environment["external_temperature"]
    wind_speed = environment["wind_speed"]
    solar_irradiance = environment["solar_irradiance"]
    visibility = environment["visibility"]

    # Summer mode: Grounded in Antarctic seasonal coastal/ice-shelf maximums
    if mode == "summer":
        external_temperature["value"] = round(random.uniform(-10.0, -2.0), 1)
        solar_irradiance["value"] = round(random.uniform(120.0, 350.0), 1)

    # Winter mode: Grounded in continental interior deep freezes and polar night flatlines
    elif mode == "winter":
        external_temperature["value"] = round(random.uniform(-65.0, -20.0), 1)
        solar_irradiance["value"] = round(random.uniform(0.0, 0.5), 1)

    # Stormy mode: Severe katabatic winds and absolute whiteout visibility scales
    elif mode == "stormy":
        wind_speed["value"] = round(random.uniform(25.0, 55.0), 2)
        visibility["value"] = round(random.uniform(0.0, 0.7), 1)
        solar_irradiance["value"] = round(random.uniform(5.0, 50.0), 1)

    # Low-fuel mode: Retain structural environment baseline but kill mechanical systems
    elif mode == "low_fuel":
        if external_temperature["value"] > -15:
            external_temperature["value"] = round(random.uniform(-10.0, -2.0), 1)
            solar_irradiance["value"] = round(random.uniform(120.0, 350.0), 1)
        else:
            external_temperature["value"] = round(random.uniform(-65.0, -20.0), 1)
            solar_irradiance["value"] = round(random.uniform(0.0, 0.5), 1)

        for generator in energy["generators"]:
            generator["status"] = "off"
            generator["output_power"] = 0
            generator["load_percent"] = 0
            generator["fuel_consumption_rate"] = 0

        for appliance in energy["consumption"]["appliances"]:
            appliance["status"] = "off"
            appliance["power"] = 0

        energy["consumption"]["total_power"] = 0

    # Bad connection mode: Caching telemetry while retaining physical conditions
    elif mode == "bad_connection":
        if external_temperature["value"] > -15:
            external_temperature["value"] = round(random.uniform(-10.0, -2.0), 1)
            solar_irradiance["value"] = round(random.uniform(120.0, 350.0), 1)
        else:
            external_temperature["value"] = round(random.uniform(-65.0, -20.0), 1)
            solar_irradiance["value"] = round(random.uniform(0.0, 0.5), 1)

    for key in timers:
        timers[key] += elapsed


def on_signal(_signal, _frame):
    global RUNNING
    RUNNING = False


def append_buffered_reading(buffer_file, reading):
    buffer_file.parent.mkdir(parents=True, exist_ok=True)
    with buffer_file.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(reading, separators=(",", ":")) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def compute_difference(current, previous):
    """Recursively eliminates fields that match the previous state structure."""
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return current

    difference = {}
    for key, val in current.items():
        if key == "timestamp":
            difference[key] = val
            continue

        if key not in previous:
            difference[key] = val
        else:
            if isinstance(val, dict) and isinstance(previous[key], dict):
                nested_diff = compute_difference(val, previous[key])
                if nested_diff:
                    difference[key] = nested_diff
            elif isinstance(val, list) and isinstance(previous[key], list):
                if json.dumps(val) != json.dumps(previous[key]):
                    difference[key] = val
            else:
                if val != previous[key]:
                    difference[key] = val

    return difference


def process_output(client, connected, topic, current_reading, last_printed_ref):
    """Filters data for updates and manages terminal printing and MQTT dispatches."""
    if last_printed_ref["state"] is None:
        payload_to_send = current_reading
    else:
        payload_to_send = compute_difference(current_reading, last_printed_ref["state"])

    last_printed_ref["state"] = copy.deepcopy(current_reading)
    print(json.dumps(payload_to_send, indent=2), flush=True)
    
    if connected["status"]:
        try:
            client.publish(topic, json.dumps(payload_to_send, separators=(",", ":")), qos=1)
        except Exception:
            pass


def drain_buffer(client, connected, topic, buffer_file, last_printed_ref):
    if not buffer_file.exists():
        return

    with buffer_file.open("r", encoding="utf-8") as source:
        lines = source.readlines()

    if not lines:
        buffer_file.unlink(missing_ok=True)
        return

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            reading = json.loads(line.strip())
            process_output(client, connected, topic, reading, last_printed_ref)
        except Exception:
            pass

    buffer_file.unlink(missing_ok=True)


def check_keyboard_input():
    global CURRENT_MODE
    mode_map = {
        's': 'summer',
        'w': 'winter',
        't': 'stormy',
        'f': 'low_fuel',
        'b': 'bad_connection'
    }
    if msvcrt.kbhit():
        try:
            char_pressed = msvcrt.getch().decode('utf-8', errors='ignore').lower()
            if char_pressed in mode_map:
                new_mode = mode_map[char_pressed]
                if new_mode != CURRENT_MODE:
                    CURRENT_MODE = new_mode
                    print(f"\n>>> MODE CHANGED TO: [{CURRENT_MODE.upper()}] <<<\n", flush=True)
        except Exception:
            pass


def main():
    global CURRENT_MODE
    parser = argparse.ArgumentParser(description="Antarctic station MET READER MQTT simulator")
    parser.add_argument("--file", default="format.json")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="antarctic/station/BHARATI")
    parser.add_argument(
        "--mode",
        choices=["summer", "winter", "stormy", "low_fuel", "bad_connection"],
        default="summer",
        help="Initial starting mode for the simulator"
    )
    parser.add_argument(
        "--buffer-file",
        default="buffered_readings.jsonl",
        help="File used to store readings waiting for MQTT delivery",
    )
    args = parser.parse_args()

    CURRENT_MODE = args.mode
    buffer_file = Path(args.buffer_file)
    
    if buffer_file.exists():
        buffer_file.unlink()

    with Path(args.file).open("r", encoding="utf-8") as source:
        state = json.load(source)

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    connected = {"status": False}

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            connected["status"] = True

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        connected["status"] = False

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.loop_start()

    try:
        client.connect_async(args.host, args.port, keepalive=60)
    except Exception:
        pass

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    timers = {
        "wind": 5,
        "weather": 60,
        "humidity": 3600,
        "indoor_temperature": 30,
    }

    last_printed_ref = {"state": None}

    initial_readings_counter = 0
    current_burst_target = random.choice([1, 2])
    is_lagging_phase = False
    lag_timer = 0.0
    current_lag_duration = random.choice([15.0, 20.0, 25.0])

    print("\n=======================================================")
    print(" DYNAMIC MET READER CONTROLLER RUNNING ")
    print(" Press a key directly in console to change modes instantly:")
    print("   [s] -> Summer Mode   [w] -> Winter Mode   [t] -> Stormy Mode")
    print("   [f] -> Low Fuel Mode [b] -> Bad Connection Mode")
    print("=======================================================\n", flush=True)

    print(f"Starting Antarctic simulation framework. Initial mode: '{CURRENT_MODE}'")

    while RUNNING:
        check_keyboard_input()
        
        current_state = copy.deepcopy(state)
        simulate(current_state, 5.0, timers, CURRENT_MODE)

        if CURRENT_MODE == "bad_connection":
            if initial_readings_counter < current_burst_target:
                process_output(client, connected, args.topic, current_state, last_printed_ref)
                initial_readings_counter += 1
            else:
                if not is_lagging_phase:
                    is_lagging_phase = True
                    lag_timer = 0.0
                    print(f"System offline (Network Lag). Appending reading to local buffer metrics: {utc_timestamp()}", flush=True)
                    append_buffered_reading(buffer_file, current_state)
                else:
                    lag_timer += 5.0
                    if lag_timer >= current_lag_duration:
                        print(f"System offline (Network Lag). Appending reading to local buffer metrics: {utc_timestamp()}", flush=True)
                        append_buffered_reading(buffer_file, current_state)
                        
                        drain_buffer(client, connected, args.topic, buffer_file, last_printed_ref)
                        
                        is_lagging_phase = False
                        initial_readings_counter = 0
                        current_burst_target = random.choice([1, 2])
                        current_lag_duration = random.uniform(15.0, 40.0)
                    else:
                        print(f"System offline (Network Lag). Appending reading to local buffer metrics: {utc_timestamp()}", flush=True)
                        append_buffered_reading(buffer_file, current_state)

        else:
            if is_lagging_phase or initial_readings_counter > 0:
                is_lagging_phase = False
                initial_readings_counter = 0
                if buffer_file.exists():
                    buffer_file.unlink()

            process_output(client, connected, args.topic, current_state, last_printed_ref)

        state = current_state
        time.sleep(5.0)

    print("\nShutting down simulation framework loop safely...", flush=True)
    client.loop_stop()


if __name__ == "__main__":
    main()