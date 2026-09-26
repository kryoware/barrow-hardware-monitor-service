"""Feeds CPU name/temp/load/clock to the Arduino Leonardo OLED stats display.

Protocol (reverse-engineered from firmware-backup.bin, a GNATSTORM Phat-Stats style sketch):
    C<temp>c<load>%|CHC<mhz>|CPU:<name>GPU:<ignored>
After a '|' the sketch drains the serial input, redraws, and clears its buffer. It rotates
screens every 18 s (big temp °C / clock MHz / load %, each under the two name lines) and
blanks the screen after ~10 s without data.

Sensors come from LibreHardwareMonitor's Remote Web Server (Options > Remote Web Server > Run).
Without it the display still shows the CPU name, with "--" for the readings.

    pip install pyserial
    python barrow.py [--port COM4] [--url http://localhost:8085/data.json] [--interval 1]
"""
import argparse
import json
import re
import textwrap
import time
import urllib.request
import winreg

import serial
import serial.tools.list_ports

LEONARDO = (0x2341, 0x8036)
TEMP_SENSORS = ("Core (Tctl/Tdie)", "CPU Package", "Core (Tctl)", "Core (Tdie)")


def cpu_name():
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
    return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()


def read_sensors(url):
    """Returns (temp °C, load %, highest core MHz); None for anything unavailable."""
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            stack = [json.load(r)]
    except (OSError, ValueError):
        return None, None, None
    temps, loads, clocks = {}, {}, []
    while stack:
        n = stack.pop()
        stack += n.get("Children", [])
        sid, text, v = n.get("SensorId", ""), n.get("Text", ""), n.get("RawValue")
        if isinstance(v, str):  # LHM 0.9.6 sends e.g. "53.8 °C", decimal comma in some locales
            m = re.match(r"-?\d+(?:[.,]\d+)?", v)
            v = float(m[0].replace(",", ".")) if m else None
        if v is None or not re.match(r"/(amd|intel)cpu/0/", sid):
            continue
        if "/temperature/" in sid:
            temps[text] = v
        elif "/load/" in sid:
            loads[text] = v
        elif "/clock/" in sid and re.fullmatch(r"Core #\d+", text):
            clocks.append(v)
    temp = next((temps[k] for k in TEMP_SENSORS if k in temps), next(iter(temps.values()), None))
    return temp, loads.get("CPU Total"), max(clocks, default=None)


def frame(name, temp, load, mhz):
    num = lambda v: "--" if v is None else f"{v:.0f}"
    l1, l2 = (textwrap.wrap(name, 20) + ["", ""])[:2]
    # The sketch only splits the name over two lines (at +21 chars) when "Intel" appears after
    # "CPU:"; otherwise it draws the same text twice. Nothing after "GPU:" is ever drawn.
    return f"C{num(temp)}c{num(load)}%|CHC{num(mhz)}|CPU:{l1:<21}{l2}GPU:Intel"


def find_port():
    for p in serial.tools.list_ports.comports():
        if (p.vid, p.pid) == LEONARDO:
            return p.device
    raise serial.SerialException("Leonardo (2341:8036) not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="default: auto-detect Leonardo")
    ap.add_argument("--url", default="http://localhost:8085/data.json")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between updates (keep < 10)")
    args = ap.parse_args()

    name, ser, last = cpu_name(), None, None
    while True:
        try:
            if ser is None:
                # Never open at 1200 baud: that resets the Leonardo into its bootloader.
                ser = serial.Serial(args.port or find_port(), 115200, timeout=1, write_timeout=2)
            data = read_sensors(args.url)
            ser.write(frame(name, *data).encode("ascii", "replace"))
            status = f"sending to {ser.port}" + ("" if data[0] is not None else f" (no sensors at {args.url})")
        except serial.SerialException as e:
            status = f"serial: {e}"
            if ser:
                ser.close()
            ser = None
        if status != last:
            print(status, flush=True)
            last = status
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
