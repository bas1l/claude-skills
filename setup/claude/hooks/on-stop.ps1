# Claude Code Stop hook: notification sound + auto-speak.
#
# Everything here is fire-and-forget: Claude Code keeps the "working" spinner up
# until every Stop hook exits, so any blocking work (speech playback, PlaySync)
# stalls the turn for as long as it runs. Each side effect is detached into its
# own process and this script returns immediately.

$hookDir   = "$env:USERPROFILE\.claude\hooks"
$flagFile  = "$hookDir\speak-auto.flag"
$debugFlag = "$hookDir\stop-hook-debug.flag"
$logFile   = "$hookDir\stop-hook-debug.log"
$soundFile = "$env:windir\Media\Windows Proximity Notification.wav"
$python    = "D:\Programming\anaconda3\envs\social-touch\python.exe"

# --- Logging (opt-in: create stop-hook-debug.flag to enable) ---
$script:debug = Test-Path $debugFlag
function Log($msg) {
    if (-not $script:debug) { return }
    if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 5MB)) {
        Remove-Item $logFile -ErrorAction SilentlyContinue
    }
    Add-Content -Path $logFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
}

# --- Detached notification sound ---
function Start-Notification {
    try {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "(New-Object System.Media.SoundPlayer '$soundFile').PlaySync()"
        )
    } catch { Log "Notification error: $_" }
}

Log "--- Hook fired (auto-speak: $(Test-Path $flagFile)) ---"

# --- Read stdin (always, so the CLI's pipe never blocks) ---
$stdinText = ""
try {
    if ([Console]::In -ne $null) { $stdinText = [Console]::In.ReadToEnd() }
    Log "Stdin length: $($stdinText.Length)"
} catch {
    Log "Stdin read error: $_"
}

if (-not (Test-Path $flagFile)) {
    Start-Notification
    Log "--- Hook done (no flag) ---"
    exit 0
}

# --- Auto-speak, detached ---
try {
    $message = ($stdinText | ConvertFrom-Json).last_assistant_message
    Log "last_assistant_message length: $(if ($message) { $message.Length } else { 'NULL' })"
    if (-not $message) {
        Start-Notification
        Log "--- Hook done (no message) ---"
        exit 0
    }

    # Drop text handoff files left behind by earlier runs (the detached speaker
    # does not clean up after itself, and must not race the parent for its own).
    Get-ChildItem "$env:TEMP\claude-speak-*.txt" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddMinutes(-10) } |
        Remove-Item -ErrorAction SilentlyContinue

    $tmpFile = "$env:TEMP\claude-speak-$([guid]::NewGuid().ToString('N')).txt"
    [System.IO.File]::WriteAllText($tmpFile, $message, [System.Text.Encoding]::UTF8)
    $rate = (Get-Content $flagFile -Raw).Trim()
    if (-not $rate) { $rate = "+0%" }
    Log "Speaking (detached) with rate: $rate"

    Start-Process $python -WindowStyle Hidden -ArgumentList @(
        "$hookDir\speak.py", $tmpFile, "en-US-JennyNeural", $rate, "--sanitize"
    )
} catch {
    Log "Auto-speak error: $_"
    Start-Notification
}

Log "--- Hook done ---"
exit 0
