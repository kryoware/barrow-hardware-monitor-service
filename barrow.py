"""Feeds CPU/GPU/RAM stats to the Arduino Leonardo OLED stats display running firmware/.

Protocol, one frame per line:
    C<temp>c<load>%|CHC<mhz>|G<gpu temp>g<gpu load>%|R<ram GB>|N<gpu name>|CPU:<name>GPU:Intel
The firmware rotates pages every 18 s (D1 temp, D2 clock, D3 load, D4 CPU/GPU/SYSRAM overview)
and blanks the screen after ~10 s without data.

Sensors come from LibreHardwareMonitor's Remote Web Server (Options > Remote Web Server > Run).
Without it the display still shows the CPU name, with "--" for the readings.

    pip install pyserial
    python barrow.py [--port COM4] [--url http://localhost:8085/data.json] [--lhm-config PATH] [--interval 1]
"""
import argparse
import base64
from http.client import HTTPException
import json
import math
import re
import textwrap
import time
import urllib.request
import winreg
import xml.etree.ElementTree as ET

import serial
import serial.tools.list_ports

LEONARDO = (0x2341, 0x8036)
TEMP_SENSORS = ("Core (Tctl/Tdie)", "CPU Package", "Core (Tctl)", "Core (Tdie)")
MAX_SENSOR_BYTES = 1024 * 1024


def cpu_name():
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
    return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()


def short_name(name):
    """'Intel(R) Core(TM) i9-10900X CPU @ 3.70GHz' -> 'Core i9-10900X', as on Barrow's product screens."""
    return " ".join(re.sub(r"^.*?\b(Intel|AMD|NVIDIA)\b|\(R\)|\(TM\)|\bCPU\b|@.*|\d+-Core Processor|Processor|with Radeon.*",
                           "", name).split())


def lhm_auth(config):
    """"user:password" for LHM's web server from its LibreHardwareMonitor.config, or None when
    authentication is off or the file is unreadable. LHM writes the file only when it exits.

    ponytail: relies on LHM 0.9.6 bug #1552: it saves SHA256(password) and hashes that again on load,
    so after one LHM restart the saved value is what the server accepts. Breaks once a release
    includes PR #2390 (saved hash then matches the real password); store that instead then.
    """
    try:
        s = {e.get("key"): e.get("value") or "" for e in ET.parse(config).iter("add")}
    except (OSError, ET.ParseError):
        return None
    if s.get("authenticationEnabled", "").lower() != "true":
        return None
    return f"{s.get('authenticationUserName', '')}:{s.get('authenticationPassword', '')}"


def read_sensors(url, auth=None):
    """Returns (temp °C, load %, highest core MHz, GPU name, GPU temp °C, GPU load %, RAM used GB);
    None ("" for the GPU name) for anything unavailable. auth is "user:password" for LHM's web server.

    Fetches LibreHardwareMonitor JSON from url with a two-second socket timeout.
    Responses over 1 MiB and transport or JSON decoding errors (including excessive
    nesting) return all fields unavailable. Invalid nodes and nonnumeric or
    nonfinite readings are skipped; numeric strings may include unit suffixes
    and a decimal comma.

    Prefers a GPU with a "GPU Core" temperature, falling back to one without it;
    ties use the lexicographically lowest hardware ID. Its name is limited to
    128 characters before vendor names and other boilerplate are removed.
    """
    headers = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()} if auth else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=2) as r:
            body = r.read(MAX_SENSOR_BYTES + 1)
        if len(body) > MAX_SENSOR_BYTES:
            raise ValueError("Sensor response exceeds 1 MiB")
        stack = [json.loads(body)]
    except (OSError, ValueError, RecursionError, HTTPException):
        return None, None, None, "", None, None, None
    temps, loads, clocks, names, gpus, ram = {}, {}, [], {}, {}, None
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        children = n.get("Children", [])
        if isinstance(children, list):
            stack.extend(children)
        sid, text, v = n.get("SensorId", ""), n.get("Text", ""), n.get("RawValue")
        if not isinstance(text, str):
            continue
        if isinstance(n.get("HardwareId"), str):
            names[n["HardwareId"]] = text[:128]
        if not isinstance(sid, str):
            continue
        if isinstance(v, str):  # LHM 0.9.6 sends e.g. "53.8 °C", decimal comma in some locales
            m = re.match(r"-?\d+(?:[.,]\d+)?", v)
            v = float(m[0].replace(",", ".")) if m else None
        if type(v) not in (int, float):
            continue
        try:
            v = float(v)
        except OverflowError:
            continue
        if not math.isfinite(v):
            continue
        hw, _, kind = sid.rpartition("/")[0].rpartition("/")
        if hw.startswith("/gpu-") and text == "GPU Core":
            gpus.setdefault(hw, {})[kind] = v
        elif sid == "/ram/data/0":
            ram = v
        elif not re.fullmatch(r"/(amd|intel)cpu/0", hw):
            continue
        elif kind == "temperature":
            temps[text] = v
        elif kind == "load":
            loads[text] = v
        elif kind == "clock" and re.fullmatch(r"Core #\d+", text):
            clocks.append(v)
    temp = next((temps[k] for k in TEMP_SENSORS if k in temps), next(iter(temps.values()), None))
    # Integrated GPUs report a "GPU Core" load but no temperature; prefer the card that has one.
    gpu = min(gpus, key=lambda h: ("temperature" not in gpus[h], h), default=None)
    g = gpus.get(gpu, {})
    return (temp, loads.get("CPU Total"), max(clocks, default=None),
            short_name(names.get(gpu, "")), g.get("temperature"), g.get("load"), ram)


def frame(name, temp, load, mhz, gpu="", gtemp=None, gload=None, ram=None):
    """Return a newline-terminated OLED protocol string for CPU/GPU/RAM readings.

    Temperatures are in °C, loads in percent, clock speed in MHz, and RAM in GB.
    None readings become "--"; RAM uses one decimal place, other readings none.
    The CPU name is wrapped to 20 characters and limited to two lines, with the
    first padded to 21 characters for the original sketch. The GPU name has
    nonprintable and non-ASCII characters and pipes removed, then is cut to 21 characters.
    """
    num = lambda v, f=".0f": "--" if v is None else f"{v:{f}}"
    gpu = re.sub(r"[^ -~]|\|", "", gpu)[:21]
    l1, l2 = (textwrap.wrap(name, 20) + ["", ""])[:2]
    # firmware/ shows only the first 19 chars of l1. The rest keeps the frame readable by the
    # original sketch: it splits the name over two lines (at +21 chars) only when "Intel" appears
    # after "CPU:", and never draws anything after "GPU:".
    return (f"C{num(temp)}c{num(load)}%|CHC{num(mhz)}|G{num(gtemp)}g{num(gload)}%|R{num(ram, '.1f')}|N{gpu}|"
            f"CPU:{l1:<21}{l2}GPU:Intel\n")


def find_port():
    for p in serial.tools.list_ports.comports():
        if (p.vid, p.pid) == LEONARDO:
            return p.device
    raise serial.SerialException("Leonardo (2341:8036) not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="default: auto-detect Leonardo")
    ap.add_argument("--url", default="http://localhost:8085/data.json")
    ap.add_argument("--lhm-config", help="LibreHardwareMonitor.config to take web server credentials from")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between updates (keep < 10)")
    args = ap.parse_args()

    name, ser, last = short_name(cpu_name()), None, None
    while True:
        try:
            if ser is None:
                # Never open at 1200 baud: that resets the Leonardo into its bootloader.
                ser = serial.Serial(args.port or find_port(), 115200, timeout=1, write_timeout=2)
            data = read_sensors(args.url, lhm_auth(args.lhm_config) if args.lhm_config else None)
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
