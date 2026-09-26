"""Feeds CPU/GPU/RAM stats to the Arduino Leonardo OLED stats display running firmware/.

Protocol, one frame per line:
    C<temp>c<load>%|CHC<mhz>|G<gpu temp>g<gpu load>%|R<ram GB>|N<gpu name>|CPU:<name>GPU:Intel
The firmware rotates pages every 18 s (D1 temp, D2 clock, D3 load, D4 CPU/GPU/SYSRAM overview)
and blanks the screen after ~10 s without data.

Sensors come from LibreHardwareMonitor's Remote Web Server (Options > Remote Web Server > Run).
Without it the display still shows the CPU name, with "--" for the readings.

    pip install pyserial
    python barrow.py [--port COM4] [--url http://localhost:8085/data.json] [--auth USER:PASSWORD] [--interval 1]
"""
import argparse
import base64
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


def short_name(name):
    """'Intel(R) Core(TM) i9-10900X CPU @ 3.70GHz' -> 'Core i9-10900X', as on Barrow's product screens."""
    return " ".join(re.sub(r"^.*?\b(Intel|AMD|NVIDIA)\b|\(R\)|\(TM\)|\bCPU\b|@.*|\d+-Core Processor|Processor|with Radeon.*",
                           "", name).split())


def read_sensors(url, auth=None):
    """Returns (temp °C, load %, highest core MHz, GPU name, GPU temp °C, GPU load %, RAM used GB);
    None ("" for the GPU name) for anything unavailable. auth is "user:password" for LHM's web server."""
    headers = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()} if auth else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=2) as r:
            stack = [json.load(r)]
        temps, loads, clocks, names, gpus, ram = {}, {}, [], {}, {}, None
        while stack:
            n = stack.pop()
            stack += n.get("Children", [])
            if "HardwareId" in n:
                names[n["HardwareId"]] = n.get("Text", "")
            sid, text, v = n.get("SensorId", ""), n.get("Text", ""), n.get("RawValue")
            if isinstance(v, str):  # LHM 0.9.6 sends e.g. "53.8 °C", decimal comma in some locales
                m = re.match(r"-?\d+(?:[.,]\d+)?", v)
                v = float(m[0].replace(",", ".")) if m else None
            if not isinstance(v, (int, float)):
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
    except Exception:  # LHM down, wrong password or unexpected JSON; raising would kill pythonw silently
        return None, None, None, "", None, None, None


def frame(name, temp, load, mhz, gpu="", gtemp=None, gload=None, ram=None):
    num = lambda v, f=".0f": "--" if v is None else f"{v:{f}}"
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
    ap.add_argument("--auth", help="USER:PASSWORD for LHM's web server (install.ps1 sets this up)")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between updates (keep < 10)")
    args = ap.parse_args()

    name, ser, last = short_name(cpu_name()), None, None
    while True:
        try:
            if ser is None:
                # Never open at 1200 baud: that resets the Leonardo into its bootloader.
                ser = serial.Serial(args.port or find_port(), 115200, timeout=1, write_timeout=2)
            data = read_sensors(args.url, args.auth)
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
