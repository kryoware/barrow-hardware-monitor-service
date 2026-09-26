# Run without elevation. All filesystem checks and system mutations are mocked.
$ErrorActionPreference = 'Stop'
foreach ($scenario in @('new', 'existing', 'missing', 'firewall-failure', 'cleanup-failure')) {
    & {
        $events = [System.Collections.Generic.List[string]]::new()
        function Test-Path { return $scenario -ne 'missing' }
        function Get-NetFirewallRule {
            if ($scenario -ne 'new') {
                return [pscustomobject]@{ Name = 'existing-rule'; Program = 'old.exe'; RemoteAddress = '127.0.0.1' }
            }
        }
        function New-NetFirewallRule {
            param($Enabled, $Profile, $Direction, $Protocol, $LocalPort, $Action, $Program, $RemoteAddress)
            if ($Enabled -ne 'True' -or $Profile -ne 'Any' -or $Direction -ne 'Inbound' -or
                $Protocol -ne 'TCP' -or $LocalPort -ne 8085 -or $Action -ne 'Block' -or
                $Program -ne 'Any' -or $RemoteAddress -ne 'Any') { throw 'Block must cover all programs and remote addresses' }
            $events.Add('firewall-new')
            if ($scenario -eq 'firewall-failure') { throw 'mock firewall failure' }
        }
        function Set-NetFirewallRule { throw 'Do not retain old rule filters' }
        function Remove-NetFirewallRule {
            param([Parameter(ValueFromPipeline)]$InputObject)
            process {
                if ($events.Count -ne 1 -or $events[0] -ne 'firewall-new' -or
                    $InputObject.Name -ne 'existing-rule') { throw 'Remove only the old rule after creating its replacement' }
                $events.Add('firewall-remove-old')
                if ($scenario -eq 'cleanup-failure') { throw 'mock cleanup failure' }
            }
        }
        function New-ScheduledTaskSettingsSet { return @{} }
        function New-ScheduledTaskTrigger { return @{} }
        function New-ScheduledTaskAction {
            param($Execute, $Argument, $WorkingDirectory)
            return @{ Execute = $Execute; Argument = $Argument }
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
            elseif ($Action.Argument -notlike "* --lhm-config `"$env:ProgramFiles\LibreHardwareMonitor\LibreHardwareMonitor.config`"") {
                throw 'Barrow must read LHM credentials from the protected config'
            }
            $events.Add("register-$TaskName")
        }
        function Start-ScheduledTask { param($TaskName) $events.Add("start-$TaskName") }

        $failure = $null
        try { & "$PSScriptRoot/install.ps1" } catch { $failure = $_.Exception.Message }
        if ($scenario -eq 'missing') {
            if ($failure -notlike 'Missing *' -or $events.Count -ne 0) { throw 'Missing-file preflight failed' }
        } elseif ($scenario -eq 'firewall-failure') {
            if ($failure -ne 'mock firewall failure' -or $events.Count -ne 1) { throw 'Installer did not fail closed' }
        } elseif ($scenario -eq 'cleanup-failure') {
            if ($failure -ne 'mock cleanup failure' -or $events.Count -ne 2) { throw 'Tasks registered after cleanup failure' }
        } else {
            $first = if ($scenario -eq 'new') { 'firewall-new' } else { 'firewall-new,firewall-remove-old' }
            $expected = "$first,register-LibreHardwareMonitor,register-Barrow OLED,start-LibreHardwareMonitor,start-Barrow OLED"
            if ($failure -or ($events -join ',') -ne $expected) { throw "Unexpected $scenario result: $failure / $events" }
        }
    }
}
Write-Output 'ok'
