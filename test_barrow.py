"""Replays the sketch's String parsing (firmware-backup.bin, ~0x48b6) on our frames. Run: python test_barrow.py"""
from barrow import frame


def screen(s):
    p, end = s.index("CPU:"), s.index("GPU:")
    off1, off2 = (4, 25) if "Intel" in s[p:] else (8, 8)
    c, lc, bar = s.index("C"), s.index("c"), s.index("|")
    h = s.index("CHC") + 3
    # Text wrap is off and lines start at x=4, so 20 whole 6 px chars fit.
    return (s[p + off1:end][:20].rstrip(), s[p + off2:end][:20].rstrip(),
            s[c + 1:lc], s[lc + 1:bar - 1], s[h:s.index("|", h)])


assert screen(frame("AMD Ryzen 7 9800X3D 8-Core Processor", 65.4, 12.3, 5225.1)) == \
    ("AMD Ryzen 7 9800X3D", "8-Core Processor", "65", "12", "5225")
assert screen(frame("Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz", 40, 100, 4700)) == \
    ("Intel(R) Core(TM)", "i7-8700K CPU @", "40", "100", "4700")
assert screen(frame("AMD Ryzen 7 9800X3D", None, None, None)) == ("AMD Ryzen 7 9800X3D", "", "--", "--", "--")

from barrow import short_name
assert short_name("Intel(R) Core(TM) i9-10900X CPU @ 3.70GHz") == "Core i9-10900X"
assert short_name("AMD Ryzen 7 9800X3D 8-Core Processor") == "Ryzen 7 9800X3D"
assert short_name("12th Gen Intel(R) Core(TM) i7-12700K") == "Core i7-12700K"

# firmware/firmware.ino parses this line; keep the two in sync.
assert frame("Ryzen 7 9800X3D", 65.4, 12.3, 5225.1, "GeForce RTX 5070 Ti", 51.7, 3, 20.66) == \
    "C65c12%|CHC5225|G52g3%|R20.7|NGeForce RTX 5070 Ti|CPU:Ryzen 7 9800X3D      GPU:Intel\n"

import json, threading, http.server
from barrow import read_sensors
tree = {"Children": [{"Children": [
    {"SensorId": "/amdcpu/0/temperature/2", "Text": "Core (Tctl/Tdie)", "RawValue": "53,8 °C"},
    {"SensorId": "/amdcpu/0/load/0", "Text": "CPU Total", "RawValue": 10.7},
    {"SensorId": "/amdcpu/0/clock/1", "Text": "Core #1", "RawValue": "5225.0 MHz"},
    {"HardwareId": "/gpu-amd/0", "Text": "AMD Radeon(TM) Graphics", "Children": [
        {"SensorId": "/gpu-amd/0/load/0", "Text": "GPU Core", "RawValue": "5.0 %"}]},
    {"HardwareId": "/gpu-nvidia/0", "Text": "NVIDIA GeForce RTX 5070 Ti", "Children": [
        {"SensorId": "/gpu-nvidia/0/temperature/0", "Text": "GPU Core", "RawValue": "40 °C"},
        {"SensorId": "/gpu-nvidia/0/load/0", "Text": "GPU Core", "RawValue": "3.0 %"}]},
    {"SensorId": "/ram/data/0", "Text": "Memory Used", "RawValue": "20.7 GB"}]}]}
H = type("H", (http.server.BaseHTTPRequestHandler,), {
    "do_GET": lambda s: (s.send_response(200 if s.headers["Authorization"] == "Basic dTpw" else 401), s.end_headers(),
                         s.wfile.write(json.dumps(tree).encode())),
    "log_message": lambda *a: None})
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=lambda: [srv.handle_request() for _ in range(3)], daemon=True).start()
url, down = f"http://127.0.0.1:{srv.server_port}/", (None, None, None, "", None, None, None)
assert read_sensors(url, "u:p") == (53.8, 10.7, 5225.0, "GeForce RTX 5070 Ti", 40.0, 3.0, 20.7)
assert read_sensors(url, "u:wrong") == down
tree = {"Children": ["x", {"Children": "ab"}, {"SensorId": 5, "RawValue": [1]}]}
assert read_sensors(url, "u:p") == down
print("ok")
