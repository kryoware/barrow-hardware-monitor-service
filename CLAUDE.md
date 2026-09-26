# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Windows-only host service that streams CPU name/temp/load/clock, GPU name/temp/load and RAM used over USB serial to an Arduino Leonardo driving a 128x64 SSD1306 OLED. `firmware/` is our own sketch for the Leonardo. `firmware-backup.bin` is a dump of the original closed third-party sketch (GNATSTORM Phat-Stats style, "USB:v1.1"): it is the restore point. Its BARROW splash bitmap is at offset 0xb10 (1024 bytes, drawBitmap format). `firmware/logo.h` now holds the nyan cat sprite for the boot animation instead.

## Commands

```sh
pip install pyserial
python barrow.py [--port COM4] [--url http://localhost:8085/data.json] [--interval 1]
python test_barrow.py        # prints "ok"; plain asserts, no test framework
```

Firmware (Arduino CLI via winget at `C:\Program Files\Arduino CLI`, core `arduino:avr`, libs Adafruit SSD1306 + NeoPixel; `directories.user` is `%LOCALAPPDATA%\Arduino15\user` because the default OneDrive Documents path doesn't exist):

```sh
arduino-cli compile --fqbn arduino:avr:leonardo firmware
# Stop the 'Barrow OLED' scheduled task first: it holds the port.
arduino-cli upload -p COM4 --fqbn arduino:avr:leonardo firmware
# Restore the original: 1200-baud touch, then within ~8 s on the bootloader port (2341:0036):
# (avrdude.exe + avrdude.conf ship in %LOCALAPPDATA%\Arduino15\packages\arduino\tools\avrdude\8.0.0-arduino1)
avrdude -C <that>/etc/avrdude.conf -p m32u4 -c avr109 -P <bootloader COM> -U flash:w:firmware-backup.bin:r
```

`install.ps1` must run elevated. It registers two logon scheduled tasks (LibreHardwareMonitor as admin, `barrow.py` via `pythonw.exe` as normal user), adds an inbound firewall block on port 8085, and starts both. It hardcodes the WinGet LHM path and Python 3.13 path under `%LOCALAPPDATA%`.

## Architecture

Data flow: LibreHardwareMonitor Remote Web Server (`/data.json`, must be enabled in LHM: Options > Remote Web Server > Run) → `read_sensors()` walks the JSON tree → `frame()` formats a protocol line → written to the Leonardo (auto-detected by VID:PID `2341:8036`) once per `--interval`.

Protocol, one `\n`-terminated line: `C<temp>c<load>%|CHC<mhz>|G<gpu temp>g<gpu load>%|R<ram GB>|N<gpu name>|CPU:<name>GPU:Intel`. `firmware.ino` `parse()` finds each field with `strstr` on its key, so keys must stay unique in the prefix. It shows the first 19 chars of the name. Pages rotate every 18 s: D1 TEMP, D2 ClocK, D3 USAGE, D4 CPU/GPU/SYSRAM overview.

The CPU name part stays readable by the original sketch, so the backup still works with this host:
- The original only splits the CPU name across two lines (second line at +21 chars) when `"Intel"` appears after `CPU:`; otherwise it draws the same text twice. So `frame()` pads line 1 to 21 chars and always ends with `GPU:Intel`.
- Each line fits 20 characters.

Constraints for both firmwares:
- The display blanks after ~10 s without data, so `--interval` must stay below 10.
- Never open the port at 1200 baud — that resets the Leonardo into its bootloader.

`test_barrow.py`:
- `screen()` re-implements the original sketch's string parsing (from firmware ~0x48b6) and asserts what it would display.
- One assert pins the exact frame that `firmware.ino` parses. If you change `frame()`, update `parse()` too.
- It spins up a local HTTP server to test `read_sensors()` against a fake LHM tree (CPU, an iGPU with load only, an NVIDIA card, RAM).

Sensor parsing handles LHM 0.9.6 sending `RawValue` as strings like `"53,8 °C"` (unit suffix, locale decimal comma). The GPU shown is the first `/gpu-*` hardware with a "GPU Core" temperature, because iGPUs report load only. Missing sensors render as `--`. The main loop reconnects on any `SerialException` and only prints status changes.
