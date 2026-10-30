#Requires -Version 7
<#
.SYNOPSIS
    Reconciles Claude Code plugins, marketplaces and user-scope MCP servers with
    setup/plugins-mcp.json, or captures that manifest from the current machine.

.DESCRIPTION
    Reconcile (default) makes the machine match the manifest:
      1. marketplaces  missing ones are added; a directory marketplace whose
                       folder is absent is first cloned from its `clone.url`
      2. plugins       user-scope plugins absent from the manifest are
                       uninstalled, missing ones installed, and the enabled
                       state is set to the manifest's
      3. marketplaces  ones absent from the manifest are removed (after step 2,
                       so their plugins are already gone)
      4. MCP servers   user-scope servers absent from the manifest are removed,
                       missing ones added, and ones whose config differs are
                       removed and re-added
    Everything already matching is left alone, so a second run does nothing.

    Capture writes the manifest from the current machine. Every `env` and
    `headers` value of an MCP server is replaced by {{env:MCP_<SERVER>_<KEY>}},
    so secrets never reach the repo; Reconcile reads them back from the
    environment and stops if one is unset.

    Out of scope: plugins and MCP servers at project or local scope (they belong
    to a repo, not the machine), `@builtin` plugins (shipped with Claude Code),
    and claude.ai connectors (they follow the account).

    Every `claude` call that fails stops the script.

.PARAMETER Mode
    Reconcile (default) or Capture.

.PARAMETER DryRun
    Reconcile: print the plan, change nothing. Capture: compare the captured
    manifest with the committed one, write nothing; exits 1 if they differ.

.EXAMPLE
    pwsh -File $HOME\.claude\skills\setup\plugins-mcp.ps1 -DryRun
    pwsh -File $HOME\.claude\skills\setup\plugins-mcp.ps1
    pwsh -File $HOME\.claude\skills\setup\plugins-mcp.ps1 -Mode Capture
#>
param(
    [ValidateSet('Reconcile', 'Capture')]
    [string]$Mode = 'Reconcile',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$manifestPath = Join-Path $PSScriptRoot 'plugins-mcp.json'
$configDir    = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { $HOME }
$claudeJson   = Join-Path $configDir '.claude.json'

function Invoke-Claude([string[]]$ClaudeArgs) {
    $out = & claude @ClaudeArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "claude $($ClaudeArgs -join ' ') failed (exit $LASTEXITCODE):`n$($out -join "`n")"
    }
    $out
}

function Get-ClaudeJson([string[]]$ClaudeArgs) {
    (Invoke-Claude $ClaudeArgs) -join "`n" | ConvertFrom-Json -AsHashtable
}

# ~ <-> $HOME, so paths in the manifest work for any user name.
function ConvertTo-PortablePath([string]$Path) {
    if ($Path.StartsWith($HOME, [StringComparison]::OrdinalIgnoreCase)) {
        return '~' + ($Path.Substring($HOME.Length) -replace '\\', '/')
    }
    $Path -replace '\\', '/'
}
function ConvertFrom-PortablePath([string]$Path) {
    $p = if ($Path.StartsWith('~')) { $HOME + $Path.Substring(1) } else { $Path }
    [IO.Path]::GetFullPath($p)
}

# Canonical JSON (sorted keys) for comparing MCP configs.
function ConvertTo-Canonical($Value) {
    if ($Value -is [System.Collections.IDictionary]) {
        $o = [ordered]@{}
        foreach ($k in ($Value.Keys | Sort-Object)) { $o[$k] = ConvertTo-Canonical $Value[$k] }
        return $o
    }
    if ($Value -is [System.Collections.IList]) { return , @($Value | ForEach-Object { ConvertTo-Canonical $_ }) }
    $Value
}
function Get-CanonicalJson($Value) { ConvertTo-Canonical $Value | ConvertTo-Json -Depth 20 -Compress }

# ── Current state ────────────────────────────────────────────────────────────
function Get-CurrentMarketplaces {
    foreach ($m in (Get-ClaudeJson 'plugin', 'marketplace', 'list', '--json')) {
        $entry = [ordered]@{ name = $m.name; source = $m.source }
        switch ($m.source) {
            'github'    { $entry.repo = $m.repo }
            'directory' {
                $entry.path = ConvertTo-PortablePath $m.path
                $top = git -C $m.path rev-parse --show-toplevel 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $url = git -C $m.path remote get-url origin
                    if ($LASTEXITCODE -ne 0) { throw "Marketplace '$($m.name)': git repo at $top has no 'origin' remote." }
                    $entry.clone = [ordered]@{ url = $url; into = ConvertTo-PortablePath ([IO.Path]::GetFullPath($top)) }
                }
            }
            default { throw "Marketplace '$($m.name)': source type '$($m.source)' is not handled by $PSCommandPath; extend it." }
        }
        $entry
    }
}

function Get-CurrentPlugins {
    Get-ClaudeJson 'plugin', 'list', '--json' |
        Where-Object { $_.scope -eq 'user' -and $_.id -notlike '*@builtin' } |
        ForEach-Object { [ordered]@{ id = $_.id; enabled = [bool]$_.enabled } }
}

function Get-CurrentMcpServers {
    if (-not (Test-Path $claudeJson)) { throw "$claudeJson not found." }
    $servers = (Get-Content $claudeJson -Raw | ConvertFrom-Json -AsHashtable).mcpServers
    if (-not $servers) { return @() }
    foreach ($name in ($servers.Keys | Sort-Object)) {
        [ordered]@{ name = $name; scope = 'user'; config = $servers[$name] }
    }
}

# ── Capture ──────────────────────────────────────────────────────────────────
function Protect-McpConfig([string]$Name, $Config) {
    $c = ConvertTo-Canonical $Config
    foreach ($field in 'env', 'headers') {
        if (-not $c.Contains($field)) { continue }
        foreach ($k in @($c[$field].Keys)) {
            $var = ('MCP_' + $Name + '_' + $k).ToUpper() -replace '[^A-Z0-9]', '_'
            $c[$field][$k] = "{{env:$var}}"
        }
    }
    $inline = @($c['url']) + @($c['args']) + @($c['command']) | Where-Object { $_ }
    foreach ($s in $inline) {
        if ($s -match '(?i)(key|token|secret|password|auth)[^/]*=') {
            throw "MCP server '$Name' has what looks like a credential inline ('$s'). Move it to env/headers before capturing."
        }
    }
    $c
}

if ($Mode -eq 'Capture') {
    $manifest = [ordered]@{
        '//'         = 'Generated by setup/plugins-mcp.ps1 -Mode Capture. A value written as env:NAME in double braces is read from environment variable NAME at install time.'
        marketplaces = @(Get-CurrentMarketplaces | Sort-Object { $_.name })
        plugins      = @(Get-CurrentPlugins | Sort-Object { $_.id })
        mcpServers   = @(Get-CurrentMcpServers | ForEach-Object {
            [ordered]@{ name = $_.name; scope = $_.scope; config = Protect-McpConfig $_.name $_.config }
        })
    }
    $text = (($manifest | ConvertTo-Json -Depth 20) -replace "`r`n", "`n") + "`n"
    if ($DryRun) {
        $committed = if (Test-Path $manifestPath) { (Get-Content $manifestPath -Raw) -replace "`r`n", "`n" } else { '' }
        if ($committed -eq $text) { Write-Host "Captured manifest matches $manifestPath."; exit 0 }
        Write-Host "Captured manifest differs from ${manifestPath}:`n$text"
        exit 1
    }
    [IO.File]::WriteAllText($manifestPath, $text)
    Write-Host "Wrote $manifestPath. Review the diff, then commit."
    exit 0
}

# ── Reconcile ────────────────────────────────────────────────────────────────
if (-not (Test-Path $manifestPath)) { throw "$manifestPath not found. Run with -Mode Capture first." }
$manifestText = Get-Content $manifestPath -Raw
$manifest = $manifestText | ConvertFrom-Json -AsHashtable

$missingVars = [regex]::Matches($manifestText, '\{\{env:([A-Za-z0-9_]+)\}\}') | ForEach-Object { $_.Groups[1].Value } |
    Sort-Object -Unique | Where-Object { [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($_)) }
if ($missingVars) {
    throw "plugins-mcp.json needs these environment variables, which are not set: $($missingVars -join ', '). Set them (user scope, e.g. [Environment]::SetEnvironmentVariable('NAME', 'value', 'User')), open a new terminal and re-run."
}
foreach ($p in $manifest.plugins) {
    $market = $p.id.Split('@')[1]
    if ($market -notin $manifest.marketplaces.name) { throw "Plugin '$($p.id)': marketplace '$market' is not listed under marketplaces in plugins-mcp.json." }
}

function Resolve-EnvRefs($Value) {
    if ($Value -is [System.Collections.IDictionary]) {
        $o = [ordered]@{}
        foreach ($k in $Value.Keys) { $o[$k] = Resolve-EnvRefs $Value[$k] }
        return $o
    }
    if ($Value -is [System.Collections.IList]) { return , @($Value | ForEach-Object { Resolve-EnvRefs $_ }) }
    if ($Value -is [string]) {
        return [regex]::Replace($Value, '\{\{env:([A-Za-z0-9_]+)\}\}', {
            param($m)
            [Environment]::GetEnvironmentVariable($m.Groups[1].Value)
        })
    }
    $Value
}

$plan = [System.Collections.Generic.List[object]]::new()
# Each step: a description and the command lines (claude args, or 'git' + args) that carry it out.
function Add-Step([string]$Text, [object[]]$Commands) { $plan.Add([pscustomobject]@{ Text = $Text; Commands = $Commands }) }

$curMarkets = @{}; foreach ($m in Get-CurrentMarketplaces) { $curMarkets[$m.name] = $m }
$curPlugins = @{}; foreach ($p in Get-CurrentPlugins) { $curPlugins[$p.id] = $p }
$curMcp     = @{}; foreach ($s in Get-CurrentMcpServers) { $curMcp[$s.name] = $s }
$wantMarkets = @{}; foreach ($m in $manifest.marketplaces) { $wantMarkets[$m.name] = $m }
$wantPlugins = @{}; foreach ($p in $manifest.plugins) { $wantPlugins[$p.id] = $p }
$wantMcp     = @{}; foreach ($s in $manifest.mcpServers) {
    if ($s.scope -ne 'user') { throw "MCP server '$($s.name)': only scope 'user' is managed, got '$($s.scope)'." }
    $wantMcp[$s.name] = $s
}

# 1. Add missing marketplaces
foreach ($m in $manifest.marketplaces) {
    if ($curMarkets.ContainsKey($m.name)) {
        $cur = $curMarkets[$m.name]
        $same = $cur.source -eq $m.source -and $cur.repo -eq $m.repo -and $cur.path -eq $m.path
        if (-not $same) { throw "Marketplace '$($m.name)' exists with a different source ($(Get-CanonicalJson $cur)). Remove it by hand or update the manifest." }
        continue
    }
    $name = $m.name
    switch ($m.source) {
        'github' {
            $repo = $m.repo
            Add-Step "add marketplace $name (github $repo)" @(, @('plugin', 'marketplace', 'add', $repo, '--scope', 'user'))
        }
        'directory' {
            $path = ConvertFrom-PortablePath $m.path
            if (-not (Test-Path $path)) {
                if (-not $m.clone) { throw "Marketplace '$name': folder $path is missing and the manifest has no clone source." }
                $url = $m.clone.url; $into = ConvertFrom-PortablePath $m.clone.into
                if (Test-Path $into) { throw "Marketplace '$name': $into exists but $path does not. Fix the checkout by hand." }
                Add-Step "clone $url -> $into" @(, @('git', 'clone', $url, $into))
            }
            Add-Step "add marketplace $name (directory $path)" @(, @('plugin', 'marketplace', 'add', $path, '--scope', 'user'))
        }
        default { throw "Marketplace '$name': source type '$($m.source)' is not handled by $PSCommandPath; extend it." }
    }
}

# 2. Plugins
foreach ($id in ($curPlugins.Keys | Sort-Object)) {
    if (-not $wantPlugins.ContainsKey($id)) {
        Add-Step "uninstall plugin $id" @(, @('plugin', 'uninstall', $id, '--scope', 'user'))
    }
}
foreach ($p in $manifest.plugins) {
    $id = $p.id
    if (-not $curPlugins.ContainsKey($id)) {
        Add-Step "install plugin $id" @(, @('plugin', 'install', $id, '--scope', 'user'))
        if (-not $p.enabled) {
            Add-Step "disable plugin $id" @(, @('plugin', 'disable', $id, '--scope', 'user'))
        }
    } elseif ($curPlugins[$id].enabled -ne [bool]$p.enabled) {
        $verb = if ($p.enabled) { 'enable' } else { 'disable' }
        Add-Step "$verb plugin $id" @(, @('plugin', $verb, $id, '--scope', 'user'))
    }
}

# 3. Remove marketplaces absent from the manifest
foreach ($name in ($curMarkets.Keys | Sort-Object)) {
    if (-not $wantMarkets.ContainsKey($name)) {
        Add-Step "remove marketplace $name" @(, @('plugin', 'marketplace', 'remove', $name))
    }
}

# 4. MCP servers (user scope)
foreach ($name in ($curMcp.Keys | Sort-Object)) {
    if (-not $wantMcp.ContainsKey($name)) {
        Add-Step "remove MCP server $name" @(, @('mcp', 'remove', $name, '--scope', 'user'))
    }
}
foreach ($s in $manifest.mcpServers) {
    $name = $s.name
    $json = Get-CanonicalJson (Resolve-EnvRefs $s.config)
    if ($curMcp.ContainsKey($name)) {
        if ((Get-CanonicalJson $curMcp[$name].config) -eq $json) { continue }
        Add-Step "replace MCP server $name (config differs)" @(
            @('mcp', 'remove', $name, '--scope', 'user'),
            @('mcp', 'add-json', $name, $json, '--scope', 'user'))
    } else {
        $type = $s.config.type
        Add-Step "add MCP server $name ($type)" @(, @('mcp', 'add-json', $name, $json, '--scope', 'user'))
    }
}

# ── Apply ────────────────────────────────────────────────────────────────────
if ($plan.Count -eq 0) {
    Write-Host 'Plugins, marketplaces and MCP servers match plugins-mcp.json: nothing to do.'
    exit 0
}
Write-Host "Plan ($($plan.Count) step(s)):"
$plan | ForEach-Object { Write-Host "    - $($_.Text)" }
if ($DryRun) { Write-Host 'Dry run: nothing changed.'; exit 0 }
foreach ($step in $plan) {
    Write-Host "`n>> $($step.Text)"
    foreach ($cmd in $step.Commands) {
        if ($cmd[0] -eq 'git') {
            git @($cmd[1..($cmd.Count - 1)]) | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "git $($cmd[1..($cmd.Count - 1)] -join ' ') failed (exit $LASTEXITCODE)." }
        } else {
            Invoke-Claude $cmd | Out-Host
        }
    }
}
Write-Host "`nDone. Restart Claude Code to load plugin and MCP changes."
