# Run elevated. See SECURITY.md before enabling the LHM web server.
# Registers logon tasks for LibreHardwareMonitor (admin, for sensor access) and
# barrow.py (normal user), blocks LHM's web server from the network, and starts both now.
$ErrorActionPreference = 'Stop'
$lhm = "$env:ProgramFiles\LibreHardwareMonitor\LibreHardwareMonitor.exe"
$pythonw = "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
$barrow = Join-Path $PSScriptRoot 'barrow.py'
$user = "$env:USERDOMAIN\$env:USERNAME"

foreach ($path in @($lhm, $pythonw, $barrow)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing $path. Follow the installation and permissions steps in SECURITY.md."
    }
}

# Establish the network block before registering anything that can start LHM.
# Create a fresh unrestricted rule before removing old rules with possibly narrower filters.
$rule = Get-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'Block LibreHardwareMonitor web (8085)' -Enabled True -Profile Any `
    -Direction Inbound -Protocol TCP -LocalPort 8085 -Action Block -Program Any -RemoteAddress Any | Out-Null
if ($rule) {
    $rule | Remove-NetFirewallRule
}

# Default task time limit is 72 h, which would kill these long-running processes.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user

Register-ScheduledTask -TaskName 'LibreHardwareMonitor' -Force -Settings $settings -Trigger $trigger `
    -Action (New-ScheduledTaskAction -Execute $lhm) `
    -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest) | Out-Null
Register-ScheduledTask -TaskName 'Barrow OLED' -Force -Settings $settings -Trigger $trigger `
    -Action (New-ScheduledTaskAction -Execute $pythonw -Argument "`"$barrow`" --lhm-config `"$([IO.Path]::ChangeExtension($lhm, '.config'))`"" -WorkingDirectory $PSScriptRoot) `
    -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited) | Out-Null

Start-ScheduledTask -TaskName 'LibreHardwareMonitor'
Start-ScheduledTask -TaskName 'Barrow OLED'
