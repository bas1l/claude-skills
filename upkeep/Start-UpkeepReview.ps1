<#
.SYNOPSIS
  Opens the latest upkeep review: its page in the default browser, and a new terminal with
  a Claude Code session in the review folder.

.DESCRIPTION
  Brings the overdue count and failures on the page up to date, then opens it. Stops loudly,
  opening nothing, if there is no report, the page is missing, or a part it needs is absent.

  Only folders named like 2026-W44 count as weeks, so a report set aside under another name is
  not taken for the latest one.

  The session is started with a plain prompt, because whether a slash command expands in an
  interactive launch is not verified (docs\verification.md, 0.5).

.PARAMETER CreateShortcut
  Creates the desktop shortcut and prints what it holds, read back from the file. Opens nothing.
  The shortcut points at the installed copy of this script, under the home directory.

.PARAMETER ShortcutFolder
  With -CreateShortcut, where to put it. The default is the desktop.

.PARAMETER PlanOnly
  Prints what would be opened, as JSON, and opens nothing.

.PARAMETER ShowErrorsInWindow
  Also shows a failure in a message window. The shortcut passes this, since its own window is
  minimized and a failure printed there would go unseen.

.EXAMPLE
  pwsh -File "$HOME\.claude\skills\upkeep\Start-UpkeepReview.ps1"
  pwsh -File "$HOME\.claude\skills\upkeep\Start-UpkeepReview.ps1" -CreateShortcut
#>
[CmdletBinding()]
param(
    [string] $ConfigPath = (Join-Path $PSScriptRoot 'config.json'),
    [switch] $CreateShortcut,
    [string] $ShortcutFolder = '',
    [switch] $PlanOnly,
    [switch] $ShowErrorsInWindow
)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8

$SESSION_PROMPT = 'Run the upkeep-review skill'
$SHORTCUT_NAME = 'Claude Upkeep Review.lnk'
$WINDOW_MINIMIZED = 7
$POPUP_ERROR_ICON = 16
$EXIT_FAILED = 1

function Expand-HomePath([string] $Path) {
    if ($Path.StartsWith('~')) { return [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE $Path.Substring(1).TrimStart('/', '\'))) }
    return [IO.Path]::GetFullPath($Path)
}

function New-ReviewShortcut {
    $home_ = $env:USERPROFILE
    if (-not $home_) { throw 'USERPROFILE is not set, so the home directory is not known.' }
    $folder = if ($ShortcutFolder) { $ShortcutFolder } else { [Environment]::GetFolderPath('Desktop') }
    if (-not (Test-Path -LiteralPath $folder)) { throw "shortcut folder not found: $folder" }
    $pwshPath = (Get-Command pwsh -ErrorAction Stop).Source
    $script = Join-Path $home_ '.claude\skills\upkeep\Start-UpkeepReview.ps1'
    $path = Join-Path $folder $SHORTCUT_NAME
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $pwshPath
    $shortcut.Arguments = "-NoProfile -WindowStyle Minimized -File `"$script`" -ShowErrorsInWindow"
    $shortcut.WorkingDirectory = $home_
    $shortcut.WindowStyle = $WINDOW_MINIMIZED
    $shortcut.Description = 'Open the Claude setup review: its page and a review session'
    $shortcut.Save()
    $saved = $shell.CreateShortcut($path)
    [ordered]@{
        shortcut = $path
        target = $saved.TargetPath
        arguments = $saved.Arguments
        working_directory = $saved.WorkingDirectory
        script_exists_yet = (Test-Path -LiteralPath $script)
    } | ConvertTo-Json
}

function Get-LatestWeekFolder([string] $ReportsDir) {
    if (-not (Test-Path -LiteralPath $ReportsDir)) { throw "No upkeep report yet: $ReportsDir does not exist. The weekly pass writes one." }
    $weeks = @(Get-ChildItem -LiteralPath $ReportsDir -Directory |
        Where-Object { $_.Name -match '^\d{4}-W\d{2}$' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'report.json')) } |
        Sort-Object Name)
    if ($weeks.Count -eq 0) { throw "No upkeep report yet under $ReportsDir. The weekly pass writes one." }
    return $weeks[-1]
}

function Start-Review {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "config file not found: $ConfigPath" }
    $config = [IO.File]::ReadAllText($ConfigPath) | ConvertFrom-Json
    $dataDir = Expand-HomePath $config.paths.data_dir
    $claudeExe = Expand-HomePath $config.paths.claude_exe
    $localSettings = Expand-HomePath $config.paths.local_settings
    $reviewDir = Join-Path $dataDir 'review'

    $week = Get-LatestWeekFolder (Join-Path $dataDir 'reports')
    $page = Join-Path $week.FullName 'review.html'
    if (-not (Test-Path -LiteralPath $page)) { throw "The review page is missing: $page. The report of $($week.Name) exists, so the weekly pass did not finish writing its review." }
    if (-not (Test-Path -LiteralPath $reviewDir)) { throw "The review folder is missing: $reviewDir" }
    if (-not (Test-Path -LiteralPath $claudeExe)) { throw "Claude Code not found: $claudeExe" }
    if (-not (Test-Path -LiteralPath $localSettings)) { throw "local settings not found: $localSettings" }
    $python = ([IO.File]::ReadAllText($localSettings) | ConvertFrom-Json).python_exe
    if (-not $python -or -not (Test-Path -LiteralPath $python)) { throw "interpreter not found: '$python', named by $localSettings" }

    $refreshed = & $python (Join-Path $PSScriptRoot 'review_data.py') refresh --config $ConfigPath 2>&1
    if ($LASTEXITCODE -ne 0) { throw "could not bring the review up to date: $refreshed" }

    $terminalArguments = "-d `"$reviewDir`" `"$claudeExe`" `"$SESSION_PROMPT`""
    if ($PlanOnly) {
        [ordered]@{ page = $page; terminal = 'wt.exe'; terminal_arguments = $terminalArguments; working_directory = $reviewDir } | ConvertTo-Json
        return
    }
    $terminal = (Get-Command wt.exe -ErrorAction Stop).Source
    Start-Process -FilePath $page
    Start-Process -FilePath $terminal -ArgumentList $terminalArguments
}

try {
    if ($CreateShortcut) { New-ReviewShortcut } else { Start-Review }
    exit 0
} catch {
    $message = "The upkeep review did not open. $($_.Exception.Message)"
    [Console]::Error.WriteLine($message)
    if ($ShowErrorsInWindow) { [void] (New-Object -ComObject WScript.Shell).Popup($message, 0, 'Upkeep review', $POPUP_ERROR_ICON) }
    exit $EXIT_FAILED
}
