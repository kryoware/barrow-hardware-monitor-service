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

import json, threading, http.server
from barrow import read_sensors
tree = {"Children": [{"Children": [
    {"SensorId": "/amdcpu/0/temperature/2", "Text": "Core (Tctl/Tdie)", "RawValue": "53,8 °C"},
    {"SensorId": "/amdcpu/0/load/0", "Text": "CPU Total", "RawValue": 10.7},
    {"SensorId": "/amdcpu/0/clock/1", "Text": "Core #1", "RawValue": "5225.0 MHz"},
    {"SensorId": "/gpu-nvidia/0/temperature/0", "Text": "GPU Core", "RawValue": "40 °C"}]}]}
H = type("H", (http.server.BaseHTTPRequestHandler,), {
    "do_GET": lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(json.dumps(tree).encode())),
    "log_message": lambda *a: None})
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.handle_request, daemon=True).start()
assert read_sensors(f"http://127.0.0.1:{srv.server_port}/") == (53.8, 10.7, 5225.0)
print("ok")
