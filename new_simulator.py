import argparse
import copy
import json
import random
import signal
import time
import os
from datetime import datetime, timezone
from pathlib import Path
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTT_ERR_SUCCESS

RUNNING = True


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
    # Insert your full simulation logic here exactly as required
    environment = state["environment"]
    internal = state["internal_conditions"]
    energy = state["energy"]
    state["timestamp"] = utc_timestamp()

    external_temperature = environment["external_temperature"]
    wind_speed = environment["wind_speed"]
    solar_irradiance = environment["solar_irradiance"]
    visibility = environment["visibility"]

    # Summer mode: external temperature remains between -10.0 and -9.0,
    # while solar irradiance remains between 120.0 and 250.0.
    if mode == "summer":
        external_temperature["value"] = round(
            random.uniform(-10.0, -9.0),
            1,
        )
        solar_irradiance["value"] = round(
            random.uniform(120.0, 250.0),
            1,
        )

    # Winter mode: external temperature remains between -21.0 and -20.0,
    # while solar irradiance stays around 0.0 and never becomes negative.
    elif mode == "winter":
        external_temperature["value"] = round(
            random.uniform(-21.0, -20.0),
            1,
        )
        solar_irradiance["value"] = round(
            random.uniform(0.0, 1.0),
            1,
        )

    # Stormy mode: wind speed rises significantly, visibility is near zero,
    # and solar irradiance remains between 10.0 and 50.0.
    elif mode == "stormy":
        wind_speed["value"] = round(
            random.uniform(25.0, 45.0),
            2,
        )
        visibility["value"] = round(
            random.uniform(0.0, 1.0),
            1,
        )
        solar_irradiance["value"] = round(
            random.uniform(10.0, 50.0),
            1,
        )

    # Low-fuel mode: retain a summer-like or winter-like environmental
    # profile according to the existing external temperature, but turn all
    # generators and appliances off.
    elif mode == "low_fuel":
        if external_temperature["value"] > -15:
            external_temperature["value"] = round(
                random.uniform(-10.0, -9.0),
                1,
            )
            solar_irradiance["value"] = round(
                random.uniform(120.0, 250.0),
                1,
            )
        else:
            external_temperature["value"] = round(
                random.uniform(-21.0, -20.0),
                1,
            )
            solar_irradiance["value"] = round(
                random.uniform(0.0, 1.0),
                1,
            )

        for generator in energy["generators"]:
            generator["status"] = "off"
            generator["output_power"] = 0
            generator["load_percent"] = 0
            generator["fuel_consumption_rate"] = 0

        for appliance in energy["consumption"]["appliances"]:
            appliance["status"] = "off"
            appliance["power"] = 0

        energy["consumption"]["total_power"] = 0

    # Bad-connection mode keeps either a summer-like or winter-like
    # temperature and solar-irradiance profile; its connection delay logic
    # remains in the main loop below.
    elif mode == "bad_connection":
        if external_temperature["value"] > -15:
            external_temperature["value"] = round(
                random.uniform(-10.0, -9.0),
                1,
            )
            solar_irradiance["value"] = round(
                random.uniform(120.0, 250.0),
                1,
            )
        else:
            external_temperature["value"] = round(
                random.uniform(-21.0, -20.0),
                1,
            )
            solar_irradiance["value"] = round(
                random.uniform(0.0, 1.0),
                1,
            )

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


def publish_reading(client, connected, topic, reading):
    if not connected["status"]:
        return False

    try:
        result = client.publish(
            topic,
            json.dumps(reading, separators=(",", ":")),
            qos=1,
            retain=False,
        )

        if result.rc != MQTT_ERR_SUCCESS:
            return False

        result.wait_for_publish(timeout=10)
        return result.is_published()

    except Exception as error:
        print(f"MQTT publish failed: {error}", flush=True)
        return False


def drain_buffer(client, connected, topic, buffer_file):
    if not connected["status"] or not buffer_file.exists():
        return

    while connected["status"]:
        with buffer_file.open("r", encoding="utf-8") as source:
            lines = source.readlines()

        if not lines:
            buffer_file.unlink(missing_ok=True)
            return

        try:
            reading = json.loads(lines[0])
        except json.JSONDecodeError:
            print("Invalid buffered reading removed", flush=True)
            remaining_lines = lines[1:]
        else:
            if not publish_reading(client, connected, topic, reading):
                return

            print(json.dumps(reading, indent=2), flush=True)
            remaining_lines = lines[1:]

        if remaining_lines:
            temporary_file = buffer_file.with_suffix(".tmp")

            with temporary_file.open("w", encoding="utf-8") as destination:
                destination.writelines(remaining_lines)
                destination.flush()
                os.fsync(destination.fileno())

            temporary_file.replace(buffer_file)
        else:
            buffer_file.unlink(missing_ok=True)
            return


def print_and_publish_reading(client, connected, topic, reading):
    print(json.dumps(reading, indent=2), flush=True)
    return publish_reading(client, connected, topic, reading)


def main():
    parser = argparse.ArgumentParser(description="Antarctic station MQTT simulator")
    parser.add_argument("--file", default="format.json")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="antarctic/station/BHARATI")
    parser.add_argument(
        "--mode",
        choices=["summer", "winter", "stormy", "low_fuel", "bad_connection"],
        default=None,
    )
    parser.add_argument(
        "--buffer-file",
        default="buffered_readings.jsonl",
        help="File used to store readings waiting for MQTT delivery",
    )
    args = parser.parse_args()

    buffer_file = Path(args.buffer_file)

    with Path(args.file).open("r", encoding="utf-8") as source:
        state = json.load(source)

    # Use MQTT v5 protocol
    client = mqtt.Client(protocol=mqtt.MQTTv5)
    connected = {"status": False}

    # Callbacks with signature updated for MQTT v5
    def on_connect(client, userdata, flags, reasonCode, properties):
        connected["status"] = True

    def on_disconnect(client, userdata, reasonCode, properties):
        connected["status"] = False

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.loop_start()

    timers = {
        "wind": 5,
        "weather": 60,
        "humidity": 3600,
        "indoor_temperature": 30,
        "food": 10800,
        "supplies": 3600,
    }

    last_time = time.monotonic()

    # Bad-connection mode variables
    normal_readings_before_delay = 3
    normal_readings_sent = 0
    delayed_readings = []
    delay_until = None
    current_delay = None

    while RUNNING:
        current_time = time.monotonic()
        elapsed = min(current_time - last_time, 5)
        last_time = current_time

        simulate(state, elapsed, timers, args.mode)

        # Maintain the existing MQTT connection behavior.
        if not connected["status"]:
            try:
                client.connect(args.host, args.port, keepalive=60)
            except Exception as error:
                print(f"MQTT unavailable: {error}", flush=True)

        if args.mode != "bad_connection":
            if not print_and_publish_reading(
                client,
                connected,
                args.topic,
                state,
            ):
                append_buffered_reading(buffer_file, state)

        elif normal_readings_sent < normal_readings_before_delay:
            print_and_publish_reading(
                client,
                connected,
                args.topic,
                state,
            )
            normal_readings_sent += 1

            if normal_readings_sent == normal_readings_before_delay:
                current_delay = random.randint(10, 40)
                delay_until = time.monotonic() + current_delay

        else:
            append_buffered_reading(buffer_file, copy.deepcopy(state))

            if time.monotonic() >= delay_until:
                drain_buffer(
                    client,
                    connected,
                    args.topic,
                    buffer_file,
                )

                current_delay = random.randint(10, 40)
                delay_until = time.monotonic() + current_delay

        time.sleep(max(0, 1 - (time.monotonic() - current_time)))

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    main()