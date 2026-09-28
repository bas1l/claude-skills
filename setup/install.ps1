#Requires -Version 7
<#
.SYNOPSIS
    Wires this skills repo into Claude Code and PowerShell on the current machine.

.DESCRIPTION
    Idempotent: run once after cloning, and again after any `git pull` that
    touches setup/. It never deletes anything; every file it changes is first
    backed up next to itself as <name>.bak-<timestamp>.

      1. ~/.claude/CLAUDE.md        -> one-line @import of setup/claude/CLAUDE.md
                                       (edits to the repo copy apply on pull, no re-run)
      2. ~/.claude/commands/*       <- copied from setup/claude/commands/
      3. ~/.claude/hooks/*          <- copied from setup/claude/hooks/
                                       (copied, not linked: the hooks keep their
                                       state flags in that folder, and Windows
                                       symlinks need admin)
      4. ~/.claude/settings.json    <- hook events from setup/settings.hooks.json,
                                       with this machine's python.exe filled in
      5. $PROFILE                   <- dot-sources setup/pwsh/cc.ps1 (the `cc` launcher)

.PARAMETER Python
    python.exe used by the TL;NR hooks (stdlib only, any Python 3 works).
    Default: first non-Store `python` on PATH, then D:\Programming\anaconda3\python.exe.

.EXAMPLE
    git clone git@github.com:bas1l/claude-skills.git $HOME\.claude\skills
    pwsh -File $HOME\.claude\skills\setup\install.ps1
#>
param(
    [string]$Python
)

$ErrorActionPreference = 'Stop'

$setupDir  = $PSScriptRoot
$claudeDir = Join-Path $HOME '.claude'
$stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'

function Backup($path) {
    if (Test-Path $path) {
        Copy-Item $path "$path.bak-$stamp"
        Write-Host "    backup: $path.bak-$stamp"
    }
}

# Copies $src to $dst unless they are already identical; backs up a differing $dst.
function Sync-File($src, $dst) {
    if ((Test-Path $dst) -and ((Get-FileHash $src).Hash -eq (Get-FileHash $dst).Hash)) {
        Write-Host "    same:   $dst"
        return
    }
    Backup $dst
    Copy-Item $src $dst -Force
    Write-Host "    copied: $dst"
}

# ── 0. Sanity ────────────────────────────────────────────────────────────────
$expectedRepo = Join-Path $claudeDir 'skills'
if ((Resolve-Path (Join-Path $setupDir '..')).Path -ne (Resolve-Path $expectedRepo -ErrorAction SilentlyContinue).Path) {
    throw "This repo must live at $expectedRepo (Claude Code loads global skills from there)."
}

if (-not $Python) {
    $Python = Get-Command python, python3 -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' } |
        Select-Object -First 1 -ExpandProperty Source
}
if (-not $Python -and (Test-Path 'D:\Programming\anaconda3\python.exe')) {
    $Python = 'D:\Programming\anaconda3\python.exe'
}
if (-not $Python -or -not (Test-Path $Python)) {
    throw "No python.exe found. Re-run with -Python <path-to-python.exe>."
}
Write-Host "Python for hooks: $Python"

# ── 1. CLAUDE.md -> @import ──────────────────────────────────────────────────
Write-Host "`n[1/5] Global CLAUDE.md"
$claudeMd = Join-Path $claudeDir 'CLAUDE.md'
$stub = "@~/.claude/skills/setup/claude/CLAUDE.md"
$current = if (Test-Path $claudeMd) { (Get-Content $claudeMd -Raw).Trim() } else { '' }
if ($current -eq $stub) {
    Write-Host "    same:   $claudeMd"
} else {
    Backup $claudeMd
    Set-Content -Path $claudeMd -Value $stub -NoNewline
    Write-Host "    wrote import stub: $claudeMd"
}

# ── 2–3. Commands and hook scripts ───────────────────────────────────────────
foreach ($sub in 'commands', 'hooks') {
    Write-Host "`n[$(if ($sub -eq 'commands') {2} else {3})/5] ~/.claude/$sub"
    $dstDir = Join-Path $claudeDir $sub
    New-Item -ItemType Directory -Force $dstDir | Out-Null
    Get-ChildItem (Join-Path $setupDir "claude\$sub") -File | ForEach-Object {
        Sync-File $_.FullName (Join-Path $dstDir $_.Name)
    }
}

# ── 4. settings.json hooks ───────────────────────────────────────────────────
Write-Host "`n[4/5] settings.json hooks"
$settingsPath = Join-Path $claudeDir 'settings.json'
$template = (Get-Content (Join-Path $setupDir 'settings.hooks.json') -Raw).
    Replace('{{PYTHON}}', ($Python -replace '\\', '/')).
    Replace('{{CLAUDE_DIR}}', ($claudeDir -replace '\\', '/')) |
    ConvertFrom-Json -AsHashtable

$settings = if (Test-Path $settingsPath) {
    Get-Content $settingsPath -Raw | ConvertFrom-Json -AsHashtable
} else { [ordered]@{} }
if (-not $settings.Contains('hooks')) { $settings['hooks'] = [ordered]@{} }

$before = $settings | ConvertTo-Json -Depth 50
foreach ($event in $template.hooks.Keys) {
    $settings.hooks[$event] = $template.hooks[$event]
}
$after = $settings | ConvertTo-Json -Depth 50
if ($before -eq $after) {
    Write-Host "    same:   $settingsPath"
} else {
    Backup $settingsPath
    Set-Content -Path $settingsPath -Value $after
    Write-Host "    updated events: $($template.hooks.Keys -join ', ')"
}

# ── 5. PowerShell profile -> cc launcher ─────────────────────────────────────
Write-Host "`n[5/5] PowerShell profile (cc launcher)"
$profilePath = $PROFILE.CurrentUserCurrentHost
$line = '. "$HOME\.claude\skills\setup\pwsh\cc.ps1"   # Claude Code `cc` launcher (claude-skills repo)'
$profileText = if (Test-Path $profilePath) { Get-Content $profilePath -Raw } else { '' }
if ($profileText -match [regex]::Escape('.claude\skills\setup\pwsh\cc.ps1')) {
    Write-Host "    same:   $profilePath"
} else {
    if ($profileText -match '(?m)^function cc\b') {
        Write-Warning "$profilePath already defines 'function cc'. The repo version is dot-sourced after it and wins; delete the old one when convenient."
    }
    New-Item -ItemType Directory -Force (Split-Path $profilePath) | Out-Null
    Backup $profilePath
    Add-Content -Path $profilePath -Value "`n$line"
    Write-Host "    added dot-source line: $profilePath"
}

Write-Host "`nDone. Open a new terminal (for cc) and restart Claude Code (for hooks and CLAUDE.md)."
