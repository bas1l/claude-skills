<#
  vscode-click-to-open.ps1 - install, activate, deactivate or query the
  open-selection-click.ahk AutoHotkey script (VS Code click-to-open hotkey).

  Active means two things together: the script is running now, and a shortcut in
  the Windows Startup folder starts it at every logon. Deactivating removes both,
  so the script stays off after a reboot. Installing and activating are the same
  operation, since AutoHotkey and the VS Code extension are prerequisites that
  this helper checks but does not install.

  The process is created through WMI (Win32_Process.Create), so its parent is not
  the Claude Code shell and it outlives the conversation.
#>
[CmdletBinding()]
param(
    [ValidateSet('activate', 'deactivate', 'status')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'

$AhkExe          = 'C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe'
$AhkScript       = 'F:\Game-Optimization\open-selection-click.ahk'
$Shortcut        = Join-Path ([Environment]::GetFolderPath('Startup')) 'open-selection-click.lnk'
$ExtensionsDir   = Join-Path $HOME '.vscode\extensions'
$ExtensionFilter = 'basil.open-external-links-*'

function Get-ScriptProcess {
    @(Get-CimInstance Win32_Process -Filter "Name LIKE 'AutoHotkey%'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$(Split-Path $AhkScript -Leaf)*" })
}

function Test-Extension {
    (Test-Path -LiteralPath $ExtensionsDir) -and
        @(Get-ChildItem -LiteralPath $ExtensionsDir -Directory -Filter $ExtensionFilter).Count -gt 0
}

function Assert-Prerequisites {
    if (-not (Test-Path -LiteralPath $AhkExe)) {
        throw "AutoHotkey v2 not found at $AhkExe"
    }
    if (-not (Test-Path -LiteralPath $AhkScript)) {
        throw "Script not found at $AhkScript"
    }
    if (-not (Test-Extension)) {
        throw "VS Code extension $ExtensionFilter not found in $ExtensionsDir. It provides the Ctrl+Alt+O command that the script sends, so the hotkey would do nothing."
    }
}

function Write-Shortcut {
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
    $link.TargetPath       = $AhkExe
    $link.Arguments        = "`"$AhkScript`""
    $link.WorkingDirectory = Split-Path $AhkScript -Parent
    $link.Save()
}

function Start-Script {
    $commandLine = '"{0}" "{1}"' -f $AhkExe, $AhkScript
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine }
    if ($result.ReturnValue -ne 0) {
        throw "Win32_Process.Create failed with return value $($result.ReturnValue) for: $commandLine"
    }
    Start-Sleep -Milliseconds 500
    if (@(Get-ScriptProcess).Count -eq 0) {
        throw "Started pid $($result.ProcessId), but no process is running $AhkScript half a second later."
    }
    return $result.ProcessId
}

function Get-State {
    $procs     = Get-ScriptProcess
    $running   = $procs.Count -gt 0
    $autostart = Test-Path -LiteralPath $Shortcut
    $state = if ($running -and $autostart) { 'ACTIVE' }
             elseif (-not $running -and -not $autostart) { 'INACTIVE' }
             else { 'PARTIAL' }
    $pidText = if ($running) { $procs.ProcessId -join ',' } else { 'none' }
    "$state running=$($running.ToString().ToLower()) pid=$pidText autostart=$($autostart.ToString().ToLower()) extension=$((Test-Extension).ToString().ToLower())"
}

switch ($Action) {
    'status' {
        Get-State
    }
    'activate' {
        Assert-Prerequisites
        Write-Shortcut
        if ((Get-ScriptProcess).Count -eq 0) { [void](Start-Script) }
        Get-State
    }
    'deactivate' {
        foreach ($p in Get-ScriptProcess) { Stop-Process -Id $p.ProcessId -Force }
        if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut -Force }
        Get-State
    }
}
