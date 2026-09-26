# Run without elevation. All filesystem checks and system mutations are mocked.
$ErrorActionPreference = 'Stop'
foreach ($scenario in @('new', 'existing', 'missing', 'firewall-failure')) {
    & {
        $events = [System.Collections.Generic.List[string]]::new()
        function Test-Path { return $scenario -ne 'missing' }
        function Get-NetFirewallRule { if ($scenario -ne 'new') { return 'existing-rule' } }
        function New-NetFirewallRule { $events.Add('firewall-new') }
        function Set-NetFirewallRule {
            $events.Add('firewall-update')
            if ($scenario -eq 'firewall-failure') { throw 'mock firewall failure' }
        }
        function Remove-NetFirewallRule { throw 'The existing block must never be removed' }
        function New-ScheduledTaskSettingsSet { return @{} }
        function New-ScheduledTaskTrigger { return @{} }
        function New-ScheduledTaskAction {
            param($Execute, $Argument, $WorkingDirectory)
            return @{ Execute = $Execute }
        }
        function New-ScheduledTaskPrincipal {
            param($UserId, $LogonType, $RunLevel)
            return @{ RunLevel = $RunLevel }
        }
        function Register-ScheduledTask {
            param($TaskName, $Action, $Principal)
            if ($events.Count -eq 0) { throw 'Task registered before firewall protection' }
            if ($TaskName -eq 'LibreHardwareMonitor') {
                if ($Action.Execute -ne "$env:ProgramFiles\LibreHardwareMonitor\LibreHardwareMonitor.exe" -or
                    $Principal.RunLevel -ne 'Highest') { throw 'Unsafe LHM task action' }
            } elseif ($Principal.RunLevel -ne 'Limited') { throw 'Barrow must not be elevated' }
            $events.Add("register-$TaskName")
        }
        function Start-ScheduledTask { param($TaskName) $events.Add("start-$TaskName") }

        $failure = $null
        try { & "$PSScriptRoot/install.ps1" } catch { $failure = $_.Exception.Message }
        if ($scenario -eq 'missing') {
            if ($failure -notlike 'Missing *' -or $events.Count -ne 0) { throw 'Missing-file preflight failed' }
        } elseif ($scenario -eq 'firewall-failure') {
            if ($failure -ne 'mock firewall failure' -or $events.Count -ne 1) { throw 'Installer did not fail closed' }
        } else {
            $first = if ($scenario -eq 'new') { 'firewall-new' } else { 'firewall-update' }
            $expected = "$first,register-LibreHardwareMonitor,register-Barrow OLED,start-LibreHardwareMonitor,start-Barrow OLED"
            if ($failure -or ($events -join ',') -ne $expected) { throw "Unexpected $scenario result: $failure / $events" }
        }
    }
}
Write-Output 'ok'
