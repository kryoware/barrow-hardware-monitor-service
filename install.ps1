# Run elevated. Registers logon tasks for LibreHardwareMonitor (admin, for sensor access) and
# barrow.py (normal user), blocks LHM's web server from the network, and starts both now.
$ErrorActionPreference = 'Stop'
$lhm = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe\LibreHardwareMonitor.exe"
$pythonw = "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
$barrow = Join-Path $PSScriptRoot 'barrow.py'
$user = "$env:USERDOMAIN\$env:USERNAME"

# Default task time limit is 72 h, which would kill these long-running processes.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user

Register-ScheduledTask -TaskName 'LibreHardwareMonitor' -Force -Settings $settings -Trigger $trigger `
    -Action (New-ScheduledTaskAction -Execute $lhm) `
    -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest) | Out-Null
Register-ScheduledTask -TaskName 'Barrow OLED' -Force -Settings $settings -Trigger $trigger `
    -Action (New-ScheduledTaskAction -Execute $pythonw -Argument "`"$barrow`"" -WorkingDirectory $PSScriptRoot) `
    -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited) | Out-Null

# LHM can't bind to 127.0.0.1 only; it listens on all interfaces. Loopback is unaffected by this rule.
Get-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' -Direction Inbound -Protocol TCP `
    -LocalPort 8085 -Action Block | Out-Null

Start-ScheduledTask -TaskName 'LibreHardwareMonitor'
Start-ScheduledTask -TaskName 'Barrow OLED'
