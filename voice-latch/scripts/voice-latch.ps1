<#
  voice-latch.ps1 - start / stop / query the voice-latch AutoHotkey script.

  The process is created through WMI (Win32_Process.Create), so its parent is
  WmiPrvSE.exe, not the Claude Code shell. It therefore survives the end of the
  conversation, the closing of the terminal, and the exit of Claude Code itself.
  It stops only on explicit stop, logoff, or reboot.
#>
[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'

$AhkExe    = 'C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe'
$AhkScript = 'F:\Game-Optimization\voice-latch.ahk'
$Marker    = 'voice-latch.ahk'

function Get-LatchProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'AutoHotkey64.exe' OR Name = 'AutoHotkey32.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Marker*" }
}

function Stop-Latch {
    $procs = @(Get-LatchProcess)
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force } catch {}
    }
    return $procs.Count
}

function Start-Latch {
    if (-not (Test-Path -LiteralPath $AhkExe))    { throw "AutoHotkey v2 not found at $AhkExe" }
    if (-not (Test-Path -LiteralPath $AhkScript)) { throw "Script not found at $AhkScript" }

    $cmd = '"{0}" "{1}"' -f $AhkExe, $AhkScript

    # Detached launch: owned by the WMI provider, not by this shell.
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
    if ($r.ReturnValue -eq 0) { return $r.ProcessId }

    # Fallback: still detaches from the shell, though less strongly.
    $p = Start-Process -FilePath $AhkExe -ArgumentList "`"$AhkScript`"" -PassThru
    return $p.Id
}

switch ($Action) {
    'status' {
        $procs = @(Get-LatchProcess)
        if ($procs.Count -gt 0) { "RUNNING pid=$($procs.ProcessId -join ',')" }
        else                    { 'STOPPED' }
    }
    'stop' {
        $n = Stop-Latch
        if ($n -gt 0) { "STOPPED ($n process(es) killed)" } else { 'STOPPED (was not running)' }
    }
    'start' {
        $procs = @(Get-LatchProcess)
        if ($procs.Count -gt 0) { "ALREADY RUNNING pid=$($procs.ProcessId -join ',')" }
        else                    { "STARTED pid=$(Start-Latch)" }
    }
    'restart' {
        [void](Stop-Latch)
        Start-Sleep -Milliseconds 400
        "RESTARTED pid=$(Start-Latch)"
    }
}
