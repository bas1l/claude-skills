<#
.SYNOPSIS
  Scheduled entry point of the upkeep passes: UTF-8, run lock, failure marker, exit code.

.DESCRIPTION
  Runs "<pass>.py run" from the configured run folder and knows nothing of what a pass
  does. The interpreter comes from the machine's local settings file named by
  paths.local_settings in config.json, as {"python_exe": "<full path>"}, because the path
  differs per machine and this repository is public. A missing file or interpreter stops
  the run.

  Exit codes: 0 clean. 1 failed. 2 another run holds the lock. 3 budget stopped, with a
  backlog.

  Lock, <data>\upkeep.lock: the process id and start time of this script and of the
  pass. A lock is live if either process still exists with that same start time, which
  rules out a reused process id. A stale lock is removed, the run goes on so that it can
  catch up, and the marker reports it. A lock that cannot be read stops the run.

  Failure marker, <data>\failure-marker.json, read by the upkeep_status hook. The file
  exists only when there is something to report:

    {"schema_version": 1,
     "entries": [{"kind": "failed|budget_stopped|stale_lock|secrets_matched|window_reset",
                  "pass": "daily", "run_id": "...", "at": "...", "exit_code": 1,
                  "summary": "one line", "failed_sessions": [...], "backlog_sessions": N,
                  "secrets_redacted": N, "details": "<path>"}]}

  A clean run of a pass clears that pass's "failed" and "budget_stopped" entries, since it
  has caught up. "stale_lock", "secrets_matched" and "window_reset" stay until someone reads them and
  deletes the entry or the file.

  A run that finds the lock held adds a "failed" entry and exits 2, because it will not run until
  its next trigger: a monthly pass refused at 03:00 would otherwise be lost silently for a month.
  The entry is written without the lock, so a pass ending at that same instant could overwrite it.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet('daily', 'weekly', 'monthly', 'research_check')] [string] $Pass,
    [string] $ConfigPath = (Join-Path $PSScriptRoot 'config.json')
)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8

$EXIT_FAILED = 1
$EXIT_LOCKED = 2
$MARKER_SCHEMA_VERSION = 1
$ERROR_TAIL_CHARS = 600

function Expand-HomePath([string] $Path) {
    if ($Path.StartsWith('~')) { return [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE $Path.Substring(1).TrimStart('/', '\'))) }
    return [IO.Path]::GetFullPath($Path)
}

function Write-JsonAtomic([string] $Path, $Value) {
    $temporary = "$Path.tmp-$PID"
    [IO.File]::WriteAllText($temporary, (ConvertTo-Json -InputObject $Value -Depth 8), $utf8)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Read-MarkerEntries([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $marker = [IO.File]::ReadAllText($Path) | ConvertFrom-Json
    if ($marker.schema_version -ne $MARKER_SCHEMA_VERSION) { throw "failure marker $Path has schema version $($marker.schema_version)" }
    return $marker.entries
}

function Save-MarkerEntries([string] $Path, $Entries) {
    if ($Entries.Count -eq 0) {
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path }
        return
    }
    Write-JsonAtomic $Path ([ordered]@{ schema_version = $MARKER_SCHEMA_VERSION; entries = @($Entries) })
}

function Add-MarkerEntry([string] $Path, [string] $Kind, [string] $Summary, [int] $ExitCode, [string] $Details, $Result) {
    $failedSessions = @()
    $backlog = 0
    $secrets = 0
    if ($null -ne $Result) {
        $failedSessions = @($Result.failed_sessions)
        $backlog = @($Result.backlog_sessions).Count
        $secrets = [int] $Result.secrets_redacted
    }
    $entry = [ordered]@{
        kind = $Kind; pass = $Pass; run_id = $runId; at = (Get-Date -Format 'o'); exit_code = $ExitCode
        summary = $Summary; failed_sessions = $failedSessions; backlog_sessions = $backlog
        secrets_redacted = $secrets; details = $Details
    }
    Save-MarkerEntries $Path (@(Read-MarkerEntries $Path) + @([pscustomobject] $entry))
}

function Test-ProcessIsLive($ProcessId, $StartTicks) {
    if ($null -eq $ProcessId) { return $false }
    $process = Get-Process -Id ([int] $ProcessId) -ErrorAction SilentlyContinue
    return ($null -ne $process) -and ($process.StartTime.ToFileTimeUtc() -eq [long] $StartTicks)
}

function New-LockDocument([string] $RunId, $ChildPid, $ChildStart) {
    return [ordered]@{
        pass = $Pass; run_id = $RunId; pid = $PID
        pid_start = (Get-Process -Id $PID).StartTime.ToFileTimeUtc()
        child_pid = $ChildPid; child_start = $ChildStart
    }
}

# Returns $true if taken, $false if a live run holds it. Sets $script:staleLock on a stale one.
function Enter-RunLock([string] $Path) {
    $body = $utf8.GetBytes((ConvertTo-Json -InputObject (New-LockDocument $runId $null $null)))
    foreach ($attempt in 1..2) {
        try {
            $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        } catch [IO.IOException] {
            if (-not (Test-Path -LiteralPath $Path)) { throw }
            try {
                $holder = [IO.File]::ReadAllText($Path) | ConvertFrom-Json
                $holderPid = $holder.pid
            } catch {
                throw "lock file $Path cannot be read: $($_.Exception.Message). Check that no run is live, then delete it."
            }
            if ($null -eq $holderPid) { throw "lock file $Path holds no process id. Check that no run is live, then delete it." }
            $script:lockHolder = $holder
            if ((Test-ProcessIsLive $holder.pid $holder.pid_start) -or (Test-ProcessIsLive $holder.child_pid $holder.child_start)) {
                return $false
            }
            $script:staleLock = $holder
            Remove-Item -LiteralPath $Path
            continue
        }
        try { $stream.Write($body, 0, $body.Length) } finally { $stream.Dispose() }
        return $true
    }
    return $false
}

if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "config file not found: $ConfigPath" }
$config = [IO.File]::ReadAllText($ConfigPath) | ConvertFrom-Json
$dataDir = Expand-HomePath $config.paths.data_dir
$runDir = Expand-HomePath $config.paths.run_dir
$localSettingsPath = Expand-HomePath $config.paths.local_settings
if (-not (Test-Path -LiteralPath $dataDir)) { throw "upkeep data folder not found: $dataDir" }

$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
$lockPath = Join-Path $dataDir 'upkeep.lock'
$markerPath = Join-Path $dataDir 'failure-marker.json'
$logDir = Join-Path $dataDir 'logs'
$script:staleLock = $null
$script:lockHolder = $null

if (-not (Enter-RunLock $lockPath)) {
    $text = "Another upkeep run is live: pass $($script:lockHolder.pass), run $($script:lockHolder.run_id), process $($script:lockHolder.pid). Lock: $lockPath"
    Add-MarkerEntry $markerPath 'failed' "$Pass pass did not start. $text" $EXIT_LOCKED $lockPath $null
    [Console]::Error.WriteLine($text)
    exit $EXIT_LOCKED
}

$exitCode = $EXIT_FAILED
$clock = [Diagnostics.Stopwatch]::StartNew()
try {
    if ($null -ne $script:staleLock) {
        $text = "Previous $($script:staleLock.pass) run $($script:staleLock.run_id) ended without releasing its lock; this run took over."
        Write-Warning $text
        Add-MarkerEntry $markerPath 'stale_lock' $text 0 $lockPath $null
    }

    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stem = Join-Path $logDir "$Pass-$runId"
    $stdoutPath = "$stem.out"
    $stderrPath = "$stem.err"
    $resultPath = "$stem.result.json"
    $result = $null

    try {
        if (-not (Test-Path -LiteralPath $localSettingsPath)) {
            throw "local settings file not found: $localSettingsPath. It must hold {`"python_exe`": `"<full path>`"}."
        }
        $python = ([IO.File]::ReadAllText($localSettingsPath) | ConvertFrom-Json).python_exe
        if ([string]::IsNullOrWhiteSpace($python)) { throw "local settings file $localSettingsPath has no python_exe" }
        if (-not (Test-Path -LiteralPath $python)) { throw "interpreter named in ${localSettingsPath} not found: $python" }
        if (-not (Test-Path -LiteralPath $runDir)) { throw "run folder not found: $runDir" }
        $passScript = Join-Path $PSScriptRoot "$Pass.py"
        if (-not (Test-Path -LiteralPath $passScript)) { throw "this pass is not built yet: $passScript" }

        $env:PYTHONUTF8 = '1'
        $arguments = @($passScript, 'run', '--config', $ConfigPath, '--run-id', $runId, '--result-file', $resultPath) |
            ForEach-Object { '"{0}"' -f $_ }
        $child = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $runDir -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $null = $child.Handle
        Write-JsonAtomic $lockPath (New-LockDocument $runId $child.Id $child.StartTime.ToFileTimeUtc())
        $child.WaitForExit()
        $exitCode = $child.ExitCode

        if (Test-Path -LiteralPath $resultPath) {
            $result = [IO.File]::ReadAllText($resultPath) | ConvertFrom-Json
        } elseif ($exitCode -eq 0) {
            throw "pass exited 0 and wrote no result file: $resultPath"
        }

        $entries = @(Read-MarkerEntries $markerPath)
        if ($exitCode -eq 0) {
            $kept = @($entries | Where-Object { -not ($_.pass -eq $Pass -and $_.kind -in @('failed', 'budget_stopped')) })
            Save-MarkerEntries $markerPath $kept
        } elseif ($null -eq $result) {
            $tail = ([IO.File]::ReadAllText($stderrPath)).Trim()
            if ($tail.Length -gt $ERROR_TAIL_CHARS) { $tail = $tail.Substring($tail.Length - $ERROR_TAIL_CHARS) }
            Add-MarkerEntry $markerPath 'failed' "$Pass pass crashed, exit $exitCode`: $tail" $exitCode $stderrPath $null
        } elseif ($result.status -eq 'budget_stopped') {
            Add-MarkerEntry $markerPath 'budget_stopped' "$Pass pass stopped at its budget; $(@($result.backlog_sessions).Count) sessions wait for the next run." $exitCode $resultPath $result
        } else {
            $why = if ($result.stop_reason) { "stopped: $($result.stop_reason)" } else { "$(@($result.failed_sessions).Count) sessions and $(@($result.memory_snapshot.errors).Count) memory folders failed" }
            Add-MarkerEntry $markerPath 'failed' "$Pass pass failed, $why" $exitCode $resultPath $result
        }
        if ($null -ne $result -and @($result.windows_reset).Count -gt 0) {
            Add-MarkerEntry $markerPath 'window_reset' "$Pass pass discarded and read again $(@($result.windows_reset).Count) windows whose records had changed." $exitCode $resultPath $result
        }
        if ($null -ne $result -and [int] $result.secrets_redacted -gt 0) {
            Add-MarkerEntry $markerPath 'secrets_matched' "$Pass pass redacted $($result.secrets_redacted) secret pattern matches; read the notes of run $runId." $exitCode $resultPath $result
        }
    } catch {
        $exitCode = $EXIT_FAILED
        Add-MarkerEntry $markerPath 'failed' "$Pass pass could not run: $($_.Exception.Message)" $exitCode $stderrPath $null
        [Console]::Error.WriteLine($_.Exception.Message)
    }

    $line = ConvertTo-Json -Compress -InputObject ([ordered]@{
        run_id = $runId; pass = $Pass; exit_code = $exitCode
        wall_seconds = [math]::Round($clock.Elapsed.TotalSeconds, 1)
        status = if ($null -ne $result) { $result.status } else { $null }
    })
    [IO.File]::AppendAllText((Join-Path $logDir 'runs.jsonl'), "$line`n", $utf8)
} finally {
    Remove-Item -LiteralPath $lockPath -ErrorAction SilentlyContinue
}
exit $exitCode
