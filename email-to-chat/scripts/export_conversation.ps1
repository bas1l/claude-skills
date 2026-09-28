<#
  export_conversation.ps1 - stage 0 of email-to-chat.

  Finds an Outlook conversation BY TITLE and exports every message in it as a
  separate .msg, so the transform never has to reconstruct a thread from one
  message's quoted trailer (which only ever contains that message's ancestor
  path, never sibling branches).

  Classic Outlook desktop only - the new Outlook (olk.exe) exposes no COM.
  Searches Inbox + Sent Items of the default account. Sent Items matters: your
  own messages often appear in nobody's trailer.

  Matching is on title alone: Subject and ConversationTopic, after stripping
  reply/forward prefixes and bracketed tags. ConversationID is deliberately not
  used. ConversationIndex IS read per item, but only to derive reply structure
  downstream - not to find anything.

  Usage
    export_conversation.ps1 -Title "Potential artifact help" -ListOnly
    export_conversation.ps1 -Title "Potential artifact help" -OutDir "C:\out"
    export_conversation.ps1 -Title "..." -OutDir "C:\out" -Group "Potential artifact help"

  Exit codes
    0  exported (or listed)
    2  several distinct conversations matched and -Group was not given
    3  nothing matched
    4  Outlook COM unavailable
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $Title,
    # where the exported .msg files land - the session folder by default
    [Parameter(Position = 1)] [string] $SourceDir,
    # scratch: _index.json here, and the merge stage adds thread.txt + images/
    [string] $WorkDir,
    [string] $Group,
    [switch] $ListOnly,
    [switch] $Recurse
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- helpers

# COM property reads throw on guarded or absent members, and try/catch is a
# statement in PowerShell - it cannot sit inline in a hashtable value. Hence a
# function rather than an inline guard at every call site.
function Get-Prop {
    param($Obj, [string] $Name, $Default = '')
    try {
        $v = $Obj.$Name
        if ($null -eq $v) { return $Default }
        return $v
    } catch { return $Default }
}

function Normalize-Title {
    param([string] $s)
    if (-not $s) { return '' }
    $t = $s
    do {
        $before = $t
        $t = $t.Trim()
        # bracketed tags Exchange/gateways prepend, e.g. [EXTERNAL], [SPAM]
        $t = $t -replace '^\[[^\]]{1,24}\]\s*', ''
        # reply/forward prefixes; a thread can mix locales when participants
        # run different Outlook languages. `_` is accepted as the separator too,
        # because a title pasted from an exported filename has had its colon
        # replaced ("FW_ TILA2 ..." rather than "FW: TILA2 ...").
        $t = $t -replace '^(RE|REPLY|FW|FWD|SV|VS|AW|WG|ANTW|TR|REF|VB)\s*[:_]\s*', ''
    } while ($t -ne $before)
    return ($t -replace '\s+', ' ').Trim()
}

function Safe-Name {
    param([string] $s, [int] $MaxLen = 60)
    $n = $s -replace '[\\/:*?"<>|\r\n\t]', '_'
    $n = $n -replace '\s+', ' '
    $n = $n.Trim().TrimEnd('.')
    if ($n.Length -gt $MaxLen) {
        $n = $n.Substring(0, $MaxLen)
        # prefer a word boundary so a truncated name stays readable
        $cut = $n.LastIndexOf(' ')
        if ($cut -ge [int]($MaxLen * 0.6)) { $n = $n.Substring(0, $cut) }
        $n = $n.Trim().TrimEnd('.', '_', '-')
    }
    if (-not $n) { $n = 'unknown' }
    return $n
}

function Get-SentTime {
    param($Item)
    foreach ($p in 'SentOn', 'ReceivedTime', 'CreationTime', 'LastModificationTime') {
        $v = Get-Prop $Item $p $null
        if ($v -is [datetime] -and $v.Year -gt 1990) { return $v }
    }
    return $null
}

function Folder-Label {
    param($Folder)
    $p = Get-Prop $Folder 'FolderPath' ''
    if ($p) { return $p }
    return (Get-Prop $Folder 'Name' '(unnamed)')
}

# ---------------------------------------------------------------- connect

try {
    $ol = New-Object -ComObject Outlook.Application
    $ns = $ol.GetNamespace('MAPI')
} catch {
    Write-Host "ERROR  cannot reach Outlook via COM: $($_.Exception.Message)"
    Write-Host "       classic Outlook desktop must be installed; the new Outlook has no COM."
    exit 4
}

$needle = Normalize-Title $Title
if (-not $needle) { Write-Host 'ERROR  -Title normalised to an empty string.'; exit 3 }
Write-Host "search       title contains: $needle"

$folders = @()
foreach ($id in @(6, 5)) {          # olFolderInbox, olFolderSentMail
    try { $folders += $ns.GetDefaultFolder($id) } catch {
        Write-Host "WARN   default folder $id unavailable: $($_.Exception.Message)"
    }
}
if ($Recurse) {
    $extra = @()
    foreach ($f in $folders) {
        try { foreach ($sub in $f.Folders) { $extra += $sub } } catch { }
    }
    $folders += $extra
}

# ---------------------------------------------------------------- collect

$hits = New-Object System.Collections.ArrayList
$skipped = New-Object System.Collections.ArrayList
$dasl = '@SQL="urn:schemas:httpmail:subject" LIKE ''%' + $needle.Replace("'", "''") + '%'''

foreach ($folder in $folders) {
    $label = Folder-Label $folder
    $candidates = $null
    try {
        $candidates = $folder.Items.Restrict($dasl)
    } catch {
        Write-Host "WARN   DASL restrict failed on $label - scanning it linearly."
        $candidates = $folder.Items
    }

    $n = 0
    foreach ($item in $candidates) {
        try {
            # 43 = olMail, 53 = olMeetingRequest. Meeting requests must be kept:
            # a thread is routinely STARTED by an invitation, and on this corpus
            # the invitation was the depth-0 root, two months earlier than every
            # reply. Dropping it loses the opening message and misdates the
            # thread. Delivery reports and everything else are still skipped.
            $cls = Get-Prop $item 'Class' 0
            if ($cls -ne 43 -and $cls -ne 53) {
                [void]$skipped.Add([pscustomobject]@{
                    folder  = $label
                    class   = $cls
                    subject = (Get-Prop $item 'Subject' '(unreadable)')
                })
                continue
            }
            $subject = Get-Prop $item 'Subject' ''
            $norm = Normalize-Title $subject
            $topic = Normalize-Title (Get-Prop $item 'ConversationTopic' '')
            if (-not $topic) { $topic = $norm }

            # title-only match, checked against both title fields
            if (($norm -notlike "*$needle*") -and ($topic -notlike "*$needle*")) { continue }

            [void]$hits.Add([pscustomobject]@{
                topic             = $topic
                subject           = $subject
                senderName        = (Get-Prop $item 'SenderName' '')
                sentOn            = (Get-SentTime $item)
                conversationIndex = (Get-Prop $item 'ConversationIndex' '')
                messageClass      = (Get-Prop $item 'MessageClass' '')
                folder            = $label
                item              = $item
            })
            $n++
        } catch {
            Write-Host "WARN   item skipped in $label : $($_.Exception.Message)"
        }
    }
    Write-Host ("folder       {0,-44} {1} hit(s)" -f $label, $n)
}

if ($hits.Count -eq 0) { Write-Host 'no messages matched that title.'; exit 3 }

# duplicates: the same message filed in two folders. ConversationIndex is unique
# per message within a conversation, so it is the dedup key; fall back to
# sender+timestamp when it is missing.
$unique = [ordered]@{}
foreach ($h in $hits) {
    $key = if ($h.conversationIndex) { $h.conversationIndex }
           else { '{0}|{1}' -f $h.senderName, $h.sentOn }
    if (-not $unique.Contains($key)) { $unique[$key] = $h }
}
$msgs = @($unique.Values) | Sort-Object sentOn
$dupes = $hits.Count - $msgs.Count

# ---------------------------------------------------------------- group

$groups = @($msgs | Group-Object topic | Sort-Object { $_.Group[0].sentOn })

Write-Host ''
Write-Host ("{0} message(s) in {1} conversation(s):" -f $msgs.Count, $groups.Count)
foreach ($g in $groups) {
    $span = @($g.Group | Sort-Object sentOn)
    $who = (@($g.Group | Select-Object -ExpandProperty senderName -Unique) | Where-Object { $_ }) -join ', '
    Write-Host ''
    Write-Host ("  topic      {0}" -f $g.Name)
    Write-Host ("  messages   {0}" -f $g.Count)
    Write-Host ("  span       {0:yyyy-MM-dd HH:mm} .. {1:yyyy-MM-dd HH:mm}" -f $span[0].sentOn, $span[-1].sentOn)
    Write-Host ("  senders    {0}" -f $who)
}

Write-Host ''
if ($dupes -gt 0) { Write-Host ("note         {0} duplicate(s) collapsed (same message in two folders)." -f $dupes) }
if ($skipped.Count -gt 0) { Write-Host ("note         {0} non-mail item(s) skipped (invites, reports)." -f $skipped.Count) }

if ($ListOnly) { exit 0 }

$chosen = $null
if ($Group) {
    $chosen = $groups | Where-Object { $_.Name -eq $Group } | Select-Object -First 1
    if (-not $chosen) { Write-Host "ERROR  no conversation with topic '$Group'."; exit 2 }
} elseif ($groups.Count -gt 1) {
    Write-Host 'ERROR  several distinct conversations share that title. Re-run with -Group "<topic>".'
    exit 2
} else {
    $chosen = $groups[0]
}

# ---------------------------------------------------------------- export

if (-not $SourceDir) { $SourceDir = (Get-Location).Path }
$null = New-Item -ItemType Directory -Force -Path $SourceDir
$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path

$ordered = @($chosen.Group | Sort-Object sentOn)

# Per-message filenames first: the longest one sets how much room is left for
# the conversation folder name inside MAX_PATH.
$seen = @{}
$names = @()
foreach ($m in $ordered) {
    $stamp = if ($m.sentOn) { $m.sentOn.ToString('yyyy-MM-dd_HHmm') } else { '0000-00-00_0000' }
    $stem = '{0}_{1}' -f $stamp, (Safe-Name $m.senderName)
    $name = $stem
    $i = 2
    while ($seen.ContainsKey($name)) { $name = '{0}_{1}' -f $stem, $i; $i++ }
    $seen[$name] = $true
    $names += $name
}
$longestMsg = ($names | Measure-Object -Property Length -Maximum).Maximum + 4   # ".msg"

# Base name: date of the FIRST message, then the conversation title. One folder
# of extracted .msg per conversation, and the .docx beside it under the same
# name, so the pairing is self-evident.
$firstDate = if ($ordered[0].sentOn) { $ordered[0].sentOn.ToString('yyyy-MM-dd') } else { '0000-00-00' }
# 260 = MAX_PATH; two separators, then room for the longest message filename
$budget = 260 - $SourceDir.Length - 2 - $longestMsg - $firstDate.Length - 1
if ($budget -lt 12) {
    Write-Host ("ERROR  -SourceDir is too long ({0} chars) to hold a conversation folder." -f $SourceDir.Length)
    Write-Host '       choose a shorter -SourceDir.'
    exit 2
}
$topicSafe = Safe-Name $chosen.Name -MaxLen ([Math]::Min(90, $budget))
$baseName = '{0}_{1}' -f $firstDate, $topicSafe
if ($topicSafe -ne (Safe-Name $chosen.Name -MaxLen 400)) {
    Write-Host ("note         folder/file name truncated to fit MAX_PATH: {0}" -f $baseName)
}

$srcDir = Join-Path $SourceDir $baseName
$docxPath = Join-Path $SourceDir "$baseName.docx"
if (-not $WorkDir) { $WorkDir = Join-Path $env:TEMP ('email-to-chat\' + $baseName) }
$null = New-Item -ItemType Directory -Force -Path $srcDir
$null = New-Item -ItemType Directory -Force -Path $WorkDir

$index = New-Object System.Collections.ArrayList

for ($k = 0; $k -lt $ordered.Count; $k++) {
    $m = $ordered[$k]
    $name = $names[$k]

    $path = Join-Path $srcDir "$name.msg"
    # Outlook's SaveAs reports a bare "The operation failed." when the target
    # exceeds MAX_PATH, which is indistinguishable from a permissions refusal.
    # Check it here so the cause is named rather than guessed.
    if ($path.Length -ge 260) {
        Write-Host ("ERROR  target path is {0} chars (limit 260): {1}" -f $path.Length, $path)
        Write-Host '       choose a shorter -SourceDir; Outlook cannot write beyond MAX_PATH.'
        continue
    }
    try {
        $m.item.SaveAs($path, 3)        # olMSG
    } catch {
        Write-Host "ERROR  SaveAs failed for '$name': $($_.Exception.Message)"
        Write-Host '       if this is the Outlook Object Model Guard, approve the prompt or set'
        Write-Host '       HKCU\Software\Policies\Microsoft\office\16.0\outlook\security\PromptOOMSaveAs = 2'
        continue
    }

    [void]$index.Add([ordered]@{
        file              = "$name.msg"
        subject           = $m.subject
        topic             = $m.topic
        senderName        = $m.senderName
        sentOn            = if ($m.sentOn) { $m.sentOn.ToString('s') } else { $null }
        conversationIndex = $m.conversationIndex
        messageClass      = $m.messageClass
        folder            = $m.folder
        bytes             = (Get-Item -LiteralPath $path).Length
    })
}

$meta = [ordered]@{
    query           = $Title
    needle          = $needle
    topic           = $chosen.Name
    baseName        = $baseName
    sourceDir       = (Resolve-Path -LiteralPath $srcDir).Path
    suggestedOutput = $docxPath
    exported        = $index.Count
    expected        = $ordered.Count
    scope           = @($folders | ForEach-Object { Folder-Label $_ })
    duplicates      = $dupes
    skippedNonMail  = $skipped.Count
    messages        = $index
}
$meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $WorkDir '_index.json') -Encoding UTF8

Write-Host ''
Write-Host ("exported     {0}/{1} message(s)" -f $index.Count, $ordered.Count)
Write-Host ("sources      {0}\" -f $srcDir)
Write-Host ("render to    {0}" -f $docxPath)
Write-Host ("workdir      {0}" -f $WorkDir)
if ($index.Count -ne $ordered.Count) { Write-Host 'WARN   some messages did not export - see errors above.' }
exit 0
