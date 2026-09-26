# barrow-service

Streams CPU name/temp/load/clock, GPU name/temp/load and RAM used from a Windows PC over USB serial to an Arduino Leonardo driving a 128x64 SSD1306 OLED.

Read [SECURITY.md](SECURITY.md) before installation. It covers the protected LHM installation, existing-task migration, and the web server's privileged hardware-control API.

## Hardware

- Arduino Leonardo (USB `2341:8036`)
- SSD1306 128x64 OLED on I2C, address `0x3C`
- Optional: 16 NeoPixels on pin 10

## Quick start

### 1. Install prerequisites

```powershell
winget install Python.Python.3.13 ArduinoSA.CLI
pip install pyserial
```

Install a fresh official LibreHardwareMonitor release and its dependencies into an administrator-controlled `%ProgramFiles%\LibreHardwareMonitor` directory as described in [SECURITY.md](SECURITY.md). Do not use the per-user WinGet installation for an elevated task.

`install.ps1` expects these exact paths:

- `%ProgramFiles%\LibreHardwareMonitor\LibreHardwareMonitor.exe`
- `%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe`

### 2. Flash the firmware

```powershell
arduino-cli core install arduino:avr
arduino-cli lib install "Adafruit SSD1306" "Adafruit NeoPixel"
arduino-cli compile --fqbn arduino:avr:leonardo firmware
arduino-cli upload -p COM4 --fqbn arduino:avr:leonardo firmware
```

Replace `COM4` with your Leonardo's port. You can find it with `arduino-cli board list`.

If `arduino-cli` fails because your Documents folder is redirected to OneDrive, point its sketchbook somewhere local:

```powershell
arduino-cli config set directories.user "$env:LOCALAPPDATA\Arduino15\user"
```

### 3. Enable the LibreHardwareMonitor web server

The web server also exposes hardware-control operations. The default client does not support authentication; see [the mitigation and remaining configuration requirements](SECURITY.md#hardware-control-api) before enabling it. Leave it disabled if those requirements cannot be met; the OLED will still show the CPU name.

1. Apply the port-8085 firewall block from SECURITY.md before enabling the server.
2. Run the protected LibreHardwareMonitor installation as administrator. It needs admin rights to read the sensors.
3. After addressing the API risk, go to **Options > Remote Web Server > Run**. The default endpoint is `http://localhost:8085/data.json`.

Open that URL in a browser to check that it returns JSON.

### 4. Test it manually

```powershell
python barrow.py
```

The Leonardo is detected automatically. The script prints `sending to COMx` once it connects. If it prints `(no sensors at ...)`, the LHM web server isn't reachable. In that case the display still shows the CPU name, with `--` for the readings.

Options:

| Flag | Default | Notes |
|------|---------|-------|
| `--port` | auto-detect | e.g. `COM4` |
| `--url` | `http://localhost:8085/data.json` | LHM endpoint |
| `--interval` | `1` | Seconds between updates. Keep it under 10, or the display blanks. |

Stop it with Ctrl+C before step 5, because only one process can hold the serial port.

### 5. Run at logon

Run this from an elevated PowerShell:

```powershell
.\install.ps1
```

This does the following:

- Establishes an inbound firewall block on port 8085 before registering the tasks. Loopback still works; this does not protect against local callers.
- Registers two logon scheduled tasks: `LibreHardwareMonitor` (runs the Program Files installation elevated) and `Barrow OLED` (runs `barrow.py` via `pythonw.exe` as your normal user, with no console window).
- Starts both tasks immediately.

## Updating the firmware later

The `Barrow OLED` task holds the serial port, so stop it before uploading:

```powershell
Stop-ScheduledTask -TaskName 'Barrow OLED'
arduino-cli upload -p COM4 --fqbn arduino:avr:leonardo firmware
Start-ScheduledTask -TaskName 'Barrow OLED'
```

## Restoring the original firmware

`firmware-backup.bin` is a dump of the original third-party sketch. `barrow.py` also works with that sketch.

1. Stop the `Barrow OLED` task, as described in the previous section.
2. Open and close the port at 1200 baud. This puts the Leonardo into its bootloader, which shows up as a new COM port with USB ID `2341:0036`:

   ```powershell
   $p = New-Object System.IO.Ports.SerialPort COM4,1200; $p.Open(); $p.Close()
   ```

3. Within about 8 seconds, flash the backup using the `avrdude` bundled in `%LOCALAPPDATA%\Arduino15\packages\arduino\tools\avrdude\8.0.0-arduino1`:

```powershell
avrdude -C <that dir>\etc\avrdude.conf -p m32u4 -c avr109 -P <bootloader COM> -U flash:w:firmware-backup.bin:r
```

## Uninstall

Run this from an elevated PowerShell:

```powershell
Stop-ScheduledTask -TaskName 'LibreHardwareMonitor'
Stop-ScheduledTask -TaskName 'Barrow OLED'
Unregister-ScheduledTask -TaskName 'LibreHardwareMonitor','Barrow OLED' -Confirm:$false
```

Exit any manually started LHM instance and disable its web server. Keep the firewall block unless LHM's web server is permanently disabled or removed; deleting scheduled tasks alone does not make the listener safe.

## Troubleshooting

- **The display is blank.** Nothing has been received for about 10 seconds. Check that the `Barrow OLED` task is running and that LHM is up.
- **`serial: could not open port`.** Another process holds the port: the scheduled task, the Arduino IDE serial monitor, or a second `barrow.py`.
- **The GPU shows `--`.** Only a GPU that reports a "GPU Core" temperature is shown. Integrated GPUs that report load only are skipped.
- **Tests:** `python test_barrow.py` prints `ok`.
- **Invalid sensor responses.** Malformed or oversized JSON produces unavailable readings; invalid nodes and nonnumeric/nonfinite values are ignored. Responses are limited to 1 MiB, and the next poll retries automatically.
