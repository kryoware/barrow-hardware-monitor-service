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
    "do_GET": lambda s: (s.send_response(200), s.end_headers(), s.wfile.write(json.dumps(tree).encode())),
    "log_message": lambda *a: None})
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.handle_request, daemon=True).start()
assert read_sensors(f"http://127.0.0.1:{srv.server_port}/") == \
    (53.8, 10.7, 5225.0, "GeForce RTX 5070 Ti", 40.0, 3.0, 20.7)
srv.server_close()

# Untrusted HTTP responses must not terminate the long-running serial service.
import io, sys
from http.client import IncompleteRead
from unittest.mock import patch, Mock
import barrow

missing = (None, None, None, "", None, None, None)
malformed = [b'[]', b'null', b'{"Children":null}', b'{"Children":{}}',
             b'{"Children":[null,[],42]}', b'{"HardwareId":[],"Text":{}}',
             b'{"SensorId":[],"RawValue":1}', b'{"Text":[],"RawValue":1}',
             b'not JSON', b'\xff', b'[' * 10000 + b'0' + b']' * 10000,
             b' ' * (barrow.MAX_SENSOR_BYTES + 1)]
for value in ({}, [], True, None, float('nan'), float('inf'), -float('inf'), 10 ** 400, '9' * 400):
    malformed.append(json.dumps({"SensorId": "/amdcpu/0/temperature/0",
                                 "Text": "CPU Package", "RawValue": value}).encode())
for body in malformed:
    with patch('barrow.urllib.request.urlopen', return_value=io.BytesIO(body)):
        assert read_sensors('http://localhost/audit') == missing, body[:80]
for error in (OSError('offline'), IncompleteRead(b'partial')):
    with patch('barrow.urllib.request.urlopen', side_effect=error):
        assert read_sensors('http://localhost/audit') == missing

mixed = {"Children": [None, {"Children": None}, tree]}
with patch('barrow.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(mixed).encode())):
    assert read_sensors('http://localhost/audit') == \
        (53.8, 10.7, 5225.0, "GeForce RTX 5070 Ti", 40.0, 3.0, 20.7)
assert len(frame('CPU', 1, 2, 3, 'X' * 10000)) < 160
assert frame('CPU', 1, 2, 3, 'bad\n|gpu').count('\n') == 1

# A bad poll followed by a valid poll recovers without reopening the serial port.
serial_port = Mock(port='audit-no-hardware')
with patch.object(sys, 'argv', ['barrow.py', '--port', 'audit-no-hardware']), \
     patch('barrow.cpu_name', return_value='AuditChip'), \
     patch('barrow.serial.Serial', return_value=serial_port) as connect, \
     patch('barrow.urllib.request.urlopen', side_effect=[io.BytesIO(b'[]'), io.BytesIO(json.dumps(tree).encode())]), \
     patch('barrow.time.sleep', side_effect=[None, KeyboardInterrupt]), patch('builtins.print'):
    try:
        barrow.main()
    except KeyboardInterrupt:
        pass
assert connect.call_count == 1
assert serial_port.write.call_count == 2
assert serial_port.write.call_args_list[0].args[0] == frame('AuditChip', *missing).encode()
assert b'C54c11%' in serial_port.write.call_args_list[1].args[0]
# Web server credentials come from LHM's config and must reach the server as Basic auth.
import os, tempfile
from barrow import lhm_auth
cfg = os.path.join(tempfile.mkdtemp(), "LibreHardwareMonitor.config")
def write_cfg(enabled):
    with open(cfg, "w") as f:
        f.write(f'<?xml version="1.0" encoding="utf-8"?><configuration><appSettings>'
                f'<add key="authenticationEnabled" value="{enabled}" /><add key="authenticationUserName" value="u" />'
                f'<add key="authenticationPassword" value="p" /></appSettings></configuration>')
write_cfg("True")
assert lhm_auth(cfg) == "u:p"
write_cfg("false")
assert lhm_auth(cfg) is None
assert lhm_auth(cfg + ".missing") is None
with open(cfg, "w") as f:
    f.write("<configuration")
assert lhm_auth(cfg) is None
for auth, header in (("u:p", "Basic dTpw"), (None, None)):
    with patch('barrow.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(tree).encode())) as get:
        assert read_sensors('http://localhost/audit', auth)[0] == 53.8
    assert get.call_args.args[0].get_header('Authorization') == header
    assert 'Authorization' not in get.call_args.args[0].headers  # unredirected: dropped on redirect
for url, sent in (('http://127.0.0.1/', True), ('http://[::1]/', True), ('https://lhm.example/', True),
                  ('http://lhm.example/', False), ('http://10.0.0.5/', False), ('file:///c:/x', False)):
    with patch('barrow.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(tree).encode())) as get:
        read_sensors(url, "u:p")
    assert get.called == sent, url
# Rejected credentials (401) must return missing, not terminate the service.
from urllib.error import HTTPError
with patch('barrow.urllib.request.urlopen', side_effect=HTTPError('http://localhost/', 401, 'Unauthorized', {}, None)):
    assert read_sensors('http://localhost/', 'u:p') == missing
print("ok")
