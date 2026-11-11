# ══════════════════════════════════════════════════════════════════════════════
# Claude Code — multi-account launcher  (PowerShell 7)
# ══════════════════════════════════════════════════════════════════════════════
# Dot-sourced from $PROFILE by setup/install.ps1:
#   . "$HOME\.claude\skills\setup\pwsh\cc.ps1"
# Edit here, not in $PROFILE; `git pull` in ~/.claude/skills updates every machine.
# ══════════════════════════════════════════════════════════════════════════════

# ── Models ──────────────────────────────────────────────────────────────────
$CLAUDE_MODEL_DEFAULT = "sonnet"
$CLAUDE_MODEL_FAST    = "haiku"
$CLAUDE_MODEL_POWER   = "opus"

# ── Smart compound launcher ──────────────────────────────────────────────────
# Usage: cc [compound] [extra claude flags]
# Compound is any combination of tokens in any order, no spaces:
#   account : 2          (omit = Account A)
#   model   : s=Sonnet   h=Haiku   o=Opus   (omit = Sonnet default)
#   perms   : dsp        (omit = normal)
#
# Examples:
#   cc           → Account A, Sonnet
#   cc dsp       → Account A, Sonnet, skip permissions
#   cc 2         → Account B, Sonnet
#   cc h         → Account A, Haiku
#   cc 2hdsp     → Account B, Haiku, skip permissions
#   cc dsp2o     → Account B, Opus, skip permissions
function cc {
    param(
        [string]$Compound = "",
        [Parameter(ValueFromRemainingArguments)]
        [string[]]$ExtraArgs
    )

    $account = ""
    $model   = $CLAUDE_MODEL_DEFAULT
    $dsp     = $false
    $title   = "🟢 Account A"
    $config  = ""

    # ── Strip known multi-char tokens first ──────────────────────────────
    $stripped = $Compound
    if ($Compound -match "dsp") { $dsp = $true;     $stripped = $stripped -replace "dsp", "" }
    if ($Compound -match "2")   { $account = "2";   $stripped = $stripped -replace "2",   "" }

    # ── Model detection on clean string ──────────────────────────────────
    if     ($stripped -match "o") { $model = $CLAUDE_MODEL_POWER }
    elseif ($stripped -match "h") { $model = $CLAUDE_MODEL_FAST }
    else                          { $model = $CLAUDE_MODEL_DEFAULT }

    # ── Resolve account ───────────────────────────────────────────────────
    if ($account -eq "2") {
        $title  = "🔵 Account B"
        $config = "$HOME\.claude-account-2"
    }

    # ── Set terminal title ────────────────────────────────────────────────
    $Host.UI.RawUI.WindowTitle = $title

    # ── Build argument list ───────────────────────────────────────────────
    $cmd = @("--model", $model)
    if ($dsp)              { $cmd += "--dangerously-skip-permissions" }
    if ($config -ne "")    { $cmd += @("--append-system-prompt", "[B]") }
    if ($ExtraArgs.Count)  { $cmd += $ExtraArgs }

    # ── Launch ────────────────────────────────────────────────────────────
    # finally, not straight-line: an aborted session must still drop
    # CLAUDE_CONFIG_DIR rather than leak Account B into the rest of the tab.
    try {
        if ($config -ne "") { $env:CLAUDE_CONFIG_DIR = $config }
        claude @cmd
    } finally {
        if (Test-Path Env:CLAUDE_CONFIG_DIR) { Remove-Item Env:CLAUDE_CONFIG_DIR }
    }
}
