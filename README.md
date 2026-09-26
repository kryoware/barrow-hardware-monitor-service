# barrow-service

Streams CPU name/temp/load/clock, GPU name/temp/load and RAM used from a Windows PC over USB serial to an Arduino Leonardo driving a 128x64 SSD1306 OLED.

## Hardware

- Arduino Leonardo (USB `2341:8036`)
- SSD1306 128x64 OLED on I2C, address `0x3C`
- Optional: 16 NeoPixels on pin 10

## Quick start

### 1. Install prerequisites

```powershell
winget install LibreHardwareMonitor.LibreHardwareMonitor Python.Python.3.13 ArduinoSA.CLI
pip install pyserial
```

`install.ps1` expects these exact paths, which are the winget defaults:

- `%LOCALAPPDATA%\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe\LibreHardwareMonitor.exe`
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

1. Run LibreHardwareMonitor as administrator. It needs admin rights to read the sensors.
2. Go to **Options > Remote Web Server > Run**. It serves `http://localhost:8085/data.json`.

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

- Registers two logon scheduled tasks: `LibreHardwareMonitor` (runs elevated) and `Barrow OLED` (runs `barrow.py` via `pythonw.exe` as your normal user, with no console window).
- Adds an inbound firewall rule that blocks port 8085. LHM listens on all interfaces, and this rule keeps it off the network. Loopback still works.
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
Unregister-ScheduledTask -TaskName 'LibreHardwareMonitor','Barrow OLED' -Confirm:$false
Remove-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)'
```

## Troubleshooting

- **The display is blank.** Nothing has been received for about 10 seconds. Check that the `Barrow OLED` task is running and that LHM is up.
- **`serial: could not open port`.** Another process holds the port: the scheduled task, the Arduino IDE serial monitor, or a second `barrow.py`.
- **The GPU shows `--`.** Only a GPU that reports a "GPU Core" temperature is shown. Integrated GPUs that report load only are skipped.
- **Tests:** `python test_barrow.py` prints `ok`.
