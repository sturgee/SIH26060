import argparse
import copy
import json
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt


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


def simulate(state, elapsed, timers):
    environment = state["environment"]
    internal = state["internal_conditions"]
    energy = state["energy"]

    state["timestamp"] = utc_timestamp()

    # Generator output, engine temperature, fuel, and battery change every second.
    for generator in energy["generators"]:
        if generator["status"] == "running":
            generator["output_power"] = round(
                clamp(perturb(generator["output_power"], 1.8), 120, generator["rated_power"]),
                1,
            )
            generator["load_percent"] = round(
                generator["output_power"] / generator["rated_power"] * 100,
                1,
            )
            generator["fuel_consumption_rate"] = round(
                generator["output_power"] * 0.225, 1
            )
            generator["fuel_remaining"] = round(
                max(
                    0,
                    generator["fuel_remaining"]
                    - generator["fuel_consumption_rate"] / 3600 * elapsed,
                ),
                2,
            )
            generator["engine_temperature"] = round(
                perturb(generator["engine_temperature"], 0.25, 65, 95), 1
            )
        else:
            generator["output_power"] = 0
            generator["load_percent"] = 0
            generator["fuel_consumption_rate"] = 0
            generator["engine_temperature"] = round(
                perturb(generator["engine_temperature"], 0.1, -20, 25), 1
            )

    # Wind changes every five seconds.
    if timers["wind"] >= 5:
        environment["wind_speed"]["value"] = round(
            perturb(environment["wind_speed"]["value"], 1.5, 0, 120), 1
        )
        environment["wind_direction"]["value"] = round(
            (environment["wind_direction"]["value"] + random.uniform(-8, 8)) % 360,
            1,
        )
        timers["wind"] = 0

    # Temperature, pressure, solar irradiance, and visibility change every minute.
    if timers["weather"] >= 60:
        environment["external_temperature"]["value"] = round(
            perturb(environment["external_temperature"]["value"], 0.4, -60, 5), 1
        )
        environment["atmospheric_pressure"]["value"] = round(
            perturb(environment["atmospheric_pressure"]["value"], 1.2, 900, 1050), 1
        )
        environment["solar_irradiance"]["value"] = round(
            perturb(environment["solar_irradiance"]["value"], 15, 0, 1200), 1
        )
        environment["visibility"]["value"] = round(
            perturb(environment["visibility"]["value"], 0.3, 0.1, 50), 1
        )
        timers["weather"] = 0

    # Humidity changes hourly.
    if timers["humidity"] >= 3600:
        environment["relative_humidity"]["value"] = round(
            perturb(environment["relative_humidity"]["value"], 2, 20, 100), 1
        )
        internal["main_building"]["humidity"]["value"] = round(
            perturb(internal["main_building"]["humidity"]["value"], 1.5, 20, 80), 1
        )
        for zone in internal["main_building"]["zones"]:
            zone["humidity"] = round(perturb(zone["humidity"], 1.5, 20, 90), 1)
        for shed in internal["sheds"]:
            shed["humidity"] = round(perturb(shed["humidity"], 1.5, 20, 90), 1)
        timers["humidity"] = 0

    # Internal temperatures change every thirty seconds.
    if timers["indoor_temperature"] >= 30:
        for zone in internal["main_building"]["zones"]:
            zone["temperature"] = round(perturb(zone["temperature"], 0.15, 10, 30), 1)
        for shed in internal["sheds"]:
            shed["temperature"] = round(perturb(shed["temperature"], 0.2, -30, 20), 1)
        internal["main_building"]["average_temperature"]["value"] = round(
            sum(zone["temperature"] for zone in internal["main_building"]["zones"])
            / len(internal["main_building"]["zones"]),
            1,
        )
        timers["indoor_temperature"] = 0

    # Food is consumed in three-hour intervals.
    if timers["food"] >= 10800:
        food = state["food"]
        food["total_remaining"] = round(
            max(0, food["total_remaining"] - food["daily_consumption"] / 8), 2
        )
        food["estimated_days_remaining"] = round(
            food["total_remaining"] / food["daily_consumption"], 1
        )
        timers["food"] = 0

    # Water and logistics fuel are updated hourly.
    if timers["supplies"] >= 3600:
        water = state["water"]
        water["fresh_water"]["remaining"] = round(
            max(0, water["fresh_water"]["remaining"]
                - water["fresh_water"]["consumption_rate"] / 24),
            2,
        )

        logistics_fuel = state["logistics"]["fuel"]
        logistics_fuel["total_remaining"] = round(
            max(0, logistics_fuel["total_remaining"]
                - logistics_fuel["daily_consumption"] / 24),
            2,
        )
        timers["supplies"] = 0

    # Recalculate power totals and battery discharge.
    total_power = sum(
        appliance["power"]
        for appliance in energy["consumption"]["appliances"]
        if appliance["status"] == "on"
    )
    energy["consumption"]["total_power"] = round(total_power, 1)

    generator_output = sum(
        generator["output_power"] for generator in energy["generators"]
    )
    battery = energy["battery"]
    battery["discharge_rate"] = round(max(0, total_power - generator_output), 1)
    battery["charge_rate"] = round(max(0, generator_output - total_power), 1)
    battery["state_of_charge"] = round(
        clamp(
            battery["state_of_charge"]
            + (battery["charge_rate"] - battery["discharge_rate"]) * elapsed
            / 3600 / battery["capacity"] * 100,
            0,
            100,
        ),
        2,
    )

    for key in timers:
        timers[key] += elapsed


def on_signal(_signal, _frame):
    global RUNNING
    RUNNING = False


def main():
    parser = argparse.ArgumentParser(description="Antarctic station MQTT simulator")
    parser.add_argument("--file", default="format.json")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="antarctic/station/BHARATI")
    args = parser.parse_args()

    with Path(args.file).open("r", encoding="utf-8") as source:
        state = json.load(source)

    client = mqtt.Client()
    connected = False

    def on_connect(_client, _userdata, _flags, _reason_code, _properties=None):
        nonlocal connected
        connected = True

    def on_disconnect(_client, _userdata, _disconnect_flags=None, _reason_code=None, _properties=None):
        nonlocal connected
        connected = False

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

    while RUNNING:
        current_time = time.monotonic()
        elapsed = min(current_time - last_time, 5)
        last_time = current_time

        simulate(state, elapsed, timers)
        mqtt_payload = json.dumps(state, separators=(",", ":"))
        terminal_payload = json.dumps(state, indent=2)

        print(terminal_payload, flush=True)

        if not connected:
            try:
                client.connect(args.host, args.port, keepalive=60)
            except OSError as error:
                print(f"MQTT unavailable: {error}", flush=True)

        if connected:
            client.publish(args.topic, mqtt_payload, qos=0, retain=False)

        time.sleep(max(0, 1 - (time.monotonic() - current_time)))

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    main()
