# Security configuration

The audit covered the host script, installer, firmware source, and this machine's task/firewall configuration. It did not audit the closed firmware backup or every transitive dependency. These changes do not migrate an existing installation automatically.

| Finding | Status in this branch | Operator action |
| --- | --- | --- |
| Elevated task executes user-writable LHM files | Installer now targets Program Files and checks that required files exist | Install trusted files with protected permissions and replace the existing task as described below |
| Unauthenticated privileged hardware-control API | Requires configuration or disabling the server; not fixed by the firewall | Apply the workaround below before enabling the web server |
| Malformed sensor JSON terminates the host | Fixed with validation, bounded reads, and regression checks | Restart Barrow from the updated checkout after migration |

## Elevated executable and dependencies

The old scheduled task runs a per-user WinGet executable with highest privileges. A normal process running as that user can modify its files. Moving only the executable is insufficient: its DLLs, configuration, directory, and parent directories must also be protected against unprivileged writes and replacement.

1. In elevated PowerShell, prevent the old task from running again and stop both tasks:

   ```powershell
   Disable-ScheduledTask -TaskName 'LibreHardwareMonitor'
   Stop-ScheduledTask -TaskName 'LibreHardwareMonitor'
   Stop-ScheduledTask -TaskName 'Barrow OLED'
   ```

   Also exit any manually launched LHM instance. Keep the firewall block in place.

2. Obtain a fresh archive from the [official LHM releases](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases). Using an elevated process, extract the complete release into a newly created `%ProgramFiles%\LibreHardwareMonitor` directory. Do not move the old per-user directory or preserve its ACLs. Reconfigure LHM from the trusted installation instead of copying old executables or configuration. The expected executable is `%ProgramFiles%\LibreHardwareMonitor\LibreHardwareMonitor.exe`.

3. Inspect permissions on the directory and its contents:

   ```powershell
   $lhmRoot = Join-Path $env:ProgramFiles 'LibreHardwareMonitor'
   Get-Acl -LiteralPath $lhmRoot | Format-List Owner,AccessToString
   icacls.exe "$lhmRoot" /T
   ```

   Administrators and SYSTEM should control writes and ownership. Ordinary users, including your individual account, should have only read/execute access. Check for explicit user write/full-control grants, writable parent directories, and junctions or links into user-writable locations. Correct unexpected permissions or reinstall into a fresh protected directory before continuing. A Program Files pathname alone is not proof of safe ACLs; the installer does not perform a complete effective-permissions or link audit. Do not make the directory user-writable to let LHM save settings; configure it while elevated.

4. Address the hardware-control API below, then run `install.ps1` from the checkout you intend to keep. It replaces the old task registration with the Program Files executable. It also registers Barrow using that checkout's absolute path. Do not delete a worktree while its task still points there. Start LHM only from the protected location and remove any old startup entries that launch the per-user copy.

5. Verify the task configuration:

   ```powershell
   (Get-ScheduledTask -TaskName 'LibreHardwareMonitor').Actions | Format-List Execute
   (Get-ScheduledTask -TaskName 'Barrow OLED').Principal | Format-List RunLevel
   ```

   LHM must point into the protected directory; Barrow must remain `Limited`. Repeat the permissions check after upgrading LHM. Do not use a per-user updater to replace elevated application files.

## Hardware-control API

LHM 0.9.6's web server is not a read-only metrics endpoint. Its [HTTP handler](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/v0.9.6/LibreHardwareMonitor/Utilities/HttpServer.cs) accepts sensor-control operations, including changes through GET requests. Local callers can reach loopback even with the inbound firewall block enabled. Binding to loopback alone does not restrict access to a particular Windows user or process.

**Immediate workaround:** turn off **Options > Remote Web Server > Run** in the protected LHM installation and save the setting. Stop/disable the LHM task as above if it cannot be configured immediately. Confirm that `http://localhost:8085/data.json` no longer responds. Barrow can still show the CPU name with `--` for readings. This loses live telemetry but removes this HTTP control surface.

To retain live telemetry, one of the following needs to be configured outside this repository:

- **Authentication, with a narrower threat model:** enable LHM's web-server authentication with a unique strong password and keep the firewall block. The client in this branch has no authentication support, so it will show unavailable readings until an authenticated client is provided. Do not embed passwords in URLs, command-line arguments, task XML, or source control. A client needs access to its credentials; authentication cannot protect against malware running as that same client account. It also does not make the API read-only.
- **Read-only integration for protection from untrusted local callers:** use an LHM build with control operations removed, or an authenticated backend behind a separately protected service that fetches only `/data.json` and publishes a read-only snapshot. A proxy must reject every other path, query, and method; do not merely block POST, because LHM also accepts control operations through GET. Keep backend credentials inaccessible to the interactive account, and ensure callers cannot bypass the proxy by reaching an unauthenticated backend. Such a service is not included here. Point Barrow's `--url` at the read-only endpoint, and update its scheduled-task arguments to use that URL as well.

Until one of those is configured and verified, leave the web server disabled. Merely rerunning `install.ps1` does not resolve this finding.

For network isolation, keep all Windows Firewall profiles enabled. Apply this rule from elevated PowerShell **before** enabling LHM's server on a fresh installation:

```powershell
New-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' -Enabled True -Profile Any -Direction Inbound -Protocol TCP -LocalPort 8085 -Action Block
```

If the rule already exists, the installer updates it without first removing it. Verify it and the firewall profiles:

```powershell
Get-NetFirewallProfile | Format-Table Name,Enabled
Get-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' | Format-List Enabled,Profile,Direction,Action
Get-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' | Get-NetFirewallPortFilter
```

The rule is specific to TCP 8085; changing LHM's port requires updating the rule and client configuration. Use HTTPS for a remote telemetry endpoint. Verify from another machine that the LHM port is unreachable. For an authenticated backend, an unauthenticated request to `/data.json` must return 401; verify control-route rejection without issuing an actual hardware-control command.

## Sensor-response handling

The reader caps each response at 1 MiB, tolerates malformed nodes, rejects invalid numeric values, and returns unavailable readings for decoding and transport errors. Invalid siblings do not hide otherwise valid sensors. GPU names are bounded before formatting and stripped of frame separators/control characters. The next poll retries without restarting the process. The HTTP socket timeout remains two seconds per blocking operation, not a total-response deadline; use a trusted local or protected telemetry endpoint.

Run the checks without touching hardware or installing tasks:

```powershell
python -B test_barrow.py
powershell -NoProfile -ExecutionPolicy Bypass -File test_install.ps1
```

The installer check mocks task and firewall commands. The execution-policy override applies only to that test process. This does not replace an elevated installation and permissions check on the target machine.
