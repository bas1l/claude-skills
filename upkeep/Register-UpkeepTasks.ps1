#Requires -Version 7
<#
.SYNOPSIS
  Registers the upkeep passes as scheduled tasks on this machine, or removes them.

.DESCRIPTION
  Idempotent: registering again replaces the same three tasks, and also re-enables one that was
  disabled. Registering an S4U task needs an elevated window (docs\verification.md, 0.6), so
  every mode except -PlanOnly checks for that first and stops with a message if it is missing.

  The tasks are written as XML because the first Saturday of a month cannot be expressed with
  New-ScheduledTaskTrigger. Trigger times have no offset, so they stay local across daylight
  saving. Settings match the Daily Brief tasks, with a 6-hour limit in place of 30 minutes.

  The tasks run the installed copy under the home directory, wherever this script was started
  from. Only tasks named in $TASKS and the research check are ever written or removed.

.PARAMETER PlanOnly
  Prints as JSON what would be done, including each definition as the Task Scheduler parsed and
  validated it, and changes nothing. Needs no elevation, and reports files that are not yet
  installed instead of stopping.

.PARAMETER Unregister
  Removes the upkeep tasks. A task that is not there is reported as absent.

.PARAMETER CheckResearch
  Runs Invoke-Upkeep.ps1 -Pass research_check once under S4U in a temporary task, waits for it,
  prints the outcome and removes the task. This does real web research with the flags of the
  weekly pass. A failure exits 1 and also leaves an entry in the failure marker.

.EXAMPLE
  pwsh -File "$HOME\.claude\skills\upkeep\Register-UpkeepTasks.ps1" -PlanOnly
#>
[CmdletBinding()]
param(
    [switch] $PlanOnly,
    [switch] $Unregister,
    [switch] $CheckResearch
)

$ErrorActionPreference = 'Stop'

$PROTECTED_TASKS = @('Claude Code Daily Brief', 'Claude Code Weekly Rollup')
$TASK_FOLDER = '\'
$RESEARCH_CHECK_TASK = 'Claude Code Upkeep Research Check'
$RESEARCH_CHECK_LIMIT = 'PT45M'
$PASS_LIMIT = 'PT6H'
$POLL_SECONDS = 5

$MONTHS = 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'
$ALL_MONTHS_MASK = 4095
$WEEK_FIRST_MASK = 1
$WEDNESDAY_MASK = 8
$SATURDAY_MASK = 64

$TRIGGER_DAILY = 2
$TRIGGER_WEEKLY = 3
$TRIGGER_MONTHLY_DOW = 5
$LOGON_S4U = 2
$TASK_VALIDATE_ONLY = 1
$TASK_CREATE_OR_UPDATE = 6
$STATE_READY = 3
$STATE_DISABLED = 1

$TASKS = @(
    [ordered]@{ name = 'Claude Code Upkeep Daily'; pass = 'daily'; schedule = 'every day at 01:00'
        triggers = @(@{ time = '01:00:00'; kind = 'daily' }) }
    [ordered]@{ name = 'Claude Code Upkeep Weekly'; pass = 'weekly'; schedule = 'every Wednesday at 02:00 and 05:30'
        triggers = @(@{ time = '02:00:00'; kind = 'wednesday' }, @{ time = '05:30:00'; kind = 'wednesday' }) }
    [ordered]@{ name = 'Claude Code Upkeep Monthly'; pass = 'monthly'; schedule = 'first Saturday of each month at 03:00'
        triggers = @(@{ time = '03:00:00'; kind = 'first_saturday' }) }
)

function Assert-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This needs an elevated window, because an S4U task can only be changed from one. Right-click PowerShell 7, choose Run as administrator, and run the same command there. Nothing was changed.'
    }
}

function Expand-HomePath([string] $Path) {
    if ($Path.StartsWith('~')) { return [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE $Path.Substring(1).TrimStart('/', '\'))) }
    return [IO.Path]::GetFullPath($Path)
}

function Get-Layout {
    if (-not $env:USERPROFILE) { throw 'USERPROFILE is not set, so the installed path is not known.' }
    $configPath = Join-Path $PSScriptRoot 'config.json'
    if (-not (Test-Path -LiteralPath $configPath)) { throw "config file not found: $configPath" }
    $config = [IO.File]::ReadAllText($configPath) | ConvertFrom-Json
    return [ordered]@{
        invoke_script = Join-Path $env:USERPROFILE '.claude\skills\upkeep\Invoke-Upkeep.ps1'
        run_dir = Expand-HomePath $config.paths.run_dir
        local_settings = Expand-HomePath $config.paths.local_settings
        data_dir = Expand-HomePath $config.paths.data_dir
        pwsh = (Get-Command pwsh -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
}

function Get-MissingParts($Layout) {
    return @(foreach ($key in 'invoke_script', 'run_dir', 'local_settings') {
            if (-not (Test-Path -LiteralPath $Layout[$key])) { "$key`: $($Layout[$key])" }
        })
}

function Assert-Installed($Layout) {
    $missing = @(Get-MissingParts $Layout)
    if ($missing.Count -gt 0) {
        throw "Upkeep is not installed here. Missing: $($missing -join '; '). Merge the skills repository first; the local settings and run folder come from the first setup. Nothing was changed."
    }
}

function Get-TriggerXml($Trigger, [string] $StartDate) {
    $boundary = "<StartBoundary>${StartDate}T$($Trigger.time)</StartBoundary>"
    $schedule = switch ($Trigger.kind) {
        'daily' { '<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>' }
        'wednesday' { '<ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Wednesday /></DaysOfWeek></ScheduleByWeek>' }
        'first_saturday' {
            $months = ($MONTHS | ForEach-Object { "<$_ />" }) -join ''
            "<ScheduleByMonthDayOfWeek><Weeks><Week>1</Week></Weeks><DaysOfWeek><Saturday /></DaysOfWeek><Months>$months</Months></ScheduleByMonthDayOfWeek>"
        }
        default { throw "unknown trigger kind: $($Trigger.kind)" }
    }
    return "<CalendarTrigger>$boundary$schedule</CalendarTrigger>"
}

function New-TaskXml([string] $Pass, [string] $Limit, $Triggers, $Layout) {
    # Starting tomorrow: a boundary in the past could count as a missed start and run at once.
    $startDate = (Get-Date).AddDays(1).ToString('yyyy-MM-dd')
    $triggerXml = (@($Triggers) | ForEach-Object { Get-TriggerXml $_ $startDate }) -join ''
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$($Layout.invoke_script)`" -Pass $Pass"
    $escape = { param($text) [Security.SecurityElement]::Escape($text) }
    return @"
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Claude Code setup upkeep, $Pass pass. See upkeep\README.md in the skills repository.</Description></RegistrationInfo>
  <Triggers>$triggerXml</Triggers>
  <Principals><Principal id="Author"><UserId>$userSid</UserId><LogonType>S4U</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>$Limit</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>$(& $escape $Layout.pwsh)</Command>
    <Arguments>$(& $escape $arguments)</Arguments>
    <WorkingDirectory>$(& $escape $Layout.run_dir)</WorkingDirectory>
  </Exec></Actions>
</Task>
"@
}

function Get-Scheduler {
    $service = New-Object -ComObject Schedule.Service
    $service.Connect()
    return $service
}

function Assert-TriggerRead($Read, $Trigger) {
    $expected = switch ($Trigger.kind) {
        'daily' { @{ Type = $TRIGGER_DAILY; DaysInterval = 1 } }
        'wednesday' { @{ Type = $TRIGGER_WEEKLY; WeeksInterval = 1; DaysOfWeek = $WEDNESDAY_MASK } }
        'first_saturday' { @{ Type = $TRIGGER_MONTHLY_DOW; WeeksOfMonth = $WEEK_FIRST_MASK; DaysOfWeek = $SATURDAY_MASK; MonthsOfYear = $ALL_MONTHS_MASK } }
    }
    foreach ($key in $expected.Keys) {
        if ($Read.$key -ne $expected[$key]) { throw "trigger $($Trigger.kind) reads back with $key=$($Read.$key), expected $($expected[$key])" }
    }
    if (-not $Read.StartBoundary.EndsWith("T$($Trigger.time)")) { throw "trigger $($Trigger.kind) reads back with a fixed offset or another time: $($Read.StartBoundary)" }
}

# Parses and validates with the same call that registers. TASK_VALIDATE_ONLY registers nothing.
function Get-CheckedDefinition($Scheduler, [string] $Name, [string] $Xml, $Triggers) {
    $Scheduler.GetFolder($TASK_FOLDER).RegisterTask($Name, $Xml, $TASK_VALIDATE_ONLY, $null, $null, $LOGON_S4U) | Out-Null
    $definition = $Scheduler.NewTask(0)
    $definition.XmlText = $Xml
    if ($definition.Principal.LogonType -ne $LOGON_S4U) { throw "$Name reads back with logon type $($definition.Principal.LogonType), expected S4U" }
    $expected = @($Triggers)
    if ($definition.Triggers.Count -ne $expected.Count) { throw "$Name reads back with $($definition.Triggers.Count) triggers, expected $($expected.Count)" }
    $read = @(foreach ($index in 1..$expected.Count) {
            $item = $definition.Triggers.Item($index)
            Assert-TriggerRead $item $expected[$index - 1]
            [ordered]@{ kind = $expected[$index - 1].kind; type = $item.Type; start_boundary = $item.StartBoundary }
        })
    return [ordered]@{
        logon_type = 'S4U'
        wake_to_run = $definition.Settings.WakeToRun
        start_when_available = $definition.Settings.StartWhenAvailable
        execution_time_limit = $definition.Settings.ExecutionTimeLimit
        triggers = $read
    }
}

function Assert-OursOnly([string] $Name) {
    if ($Name -in $PROTECTED_TASKS) { throw "refusing to touch $Name" }
}

function Show-Plan($Scheduler, $Layout) {
    $missing = @(Get-MissingParts $Layout)
    $plan = [ordered]@{ mode = 'register'; ready_to_register = ($missing.Count -eq 0); missing = $missing; layout = $Layout }
    if ($Unregister) {
        $plan = [ordered]@{ mode = 'unregister'; would_remove = @($TASKS | ForEach-Object { $_.name }) }
    } elseif ($CheckResearch) {
        $triggers = @()
        $xml = New-TaskXml 'research_check' $RESEARCH_CHECK_LIMIT $triggers $Layout
        $Scheduler.GetFolder($TASK_FOLDER).RegisterTask($RESEARCH_CHECK_TASK, $xml, $TASK_VALIDATE_ONLY, $null, $null, $LOGON_S4U) | Out-Null
        $plan.mode = 'check_research'
        $plan.temporary_task = [ordered]@{ name = $RESEARCH_CHECK_TASK; xml = $xml }
    } else {
        $plan.tasks = @(foreach ($task in $TASKS) {
                $xml = New-TaskXml $task.pass $PASS_LIMIT $task.triggers $Layout
                [ordered]@{
                    name = $task.name; pass = $task.pass; schedule = $task.schedule
                    checked = Get-CheckedDefinition $Scheduler $task.name $xml $task.triggers
                    xml = $xml
                }
            })
    }
    $plan | ConvertTo-Json -Depth 8
}

function Register-Tasks($Scheduler, $Layout) {
    Assert-Installed $Layout
    $folder = $Scheduler.GetFolder($TASK_FOLDER)
    foreach ($task in $TASKS) {
        Assert-OursOnly $task.name
        $xml = New-TaskXml $task.pass $PASS_LIMIT $task.triggers $Layout
        Get-CheckedDefinition $Scheduler $task.name $xml $task.triggers | Out-Null
        $folder.RegisterTask($task.name, $xml, $TASK_CREATE_OR_UPDATE, $null, $null, $LOGON_S4U) | Out-Null
        $logon = $folder.GetTask($task.name).Definition.Principal.LogonType
        if ($logon -ne $LOGON_S4U) { throw "$($task.name) registered with logon type $logon, expected S4U" }
        Write-Host "    registered: $($task.name), $($task.schedule)"
    }
}

function Unregister-Tasks($Scheduler) {
    $folder = $Scheduler.GetFolder($TASK_FOLDER)
    foreach ($task in $TASKS) {
        Assert-OursOnly $task.name
        if (Get-ScheduledTask -TaskPath $TASK_FOLDER -TaskName $task.name -ErrorAction SilentlyContinue) {
            $folder.DeleteTask($task.name, 0)
            Write-Host "    removed: $($task.name)"
        } else {
            Write-Host "    absent:  $($task.name)"
        }
    }
}

function Invoke-ResearchCheck($Scheduler, $Layout) {
    Assert-Installed $Layout
    Assert-OursOnly $RESEARCH_CHECK_TASK
    $folder = $Scheduler.GetFolder($TASK_FOLDER)
    $xml = New-TaskXml 'research_check' $RESEARCH_CHECK_LIMIT @() $Layout
    $registered = $folder.RegisterTask($RESEARCH_CHECK_TASK, $xml, $TASK_CREATE_OR_UPDATE, $null, $null, $LOGON_S4U)
    try {
        $registered.Run($null) | Out-Null
        Write-Host "    research check running under S4U; this takes some minutes"
        do {
            Start-Sleep -Seconds $POLL_SECONDS
            $current = $folder.GetTask($RESEARCH_CHECK_TASK)
        } while ($current.State -notin @($STATE_READY, $STATE_DISABLED))
        $taskResult = $current.LastTaskResult
    } finally {
        $folder.DeleteTask($RESEARCH_CHECK_TASK, 0)
    }
    $logDir = Join-Path $Layout.data_dir 'logs'
    $latest = Get-ChildItem -LiteralPath $logDir -Filter 'research_check-*.result.json' | Sort-Object Name | Select-Object -Last 1
    if ($taskResult -ne 0) {
        $detail = if ($latest) { [IO.File]::ReadAllText($latest.FullName) } else { 'no result file; see the .err file of this run in ' + $logDir }
        throw "RESEARCH CHECK FAILED under S4U: task result $taskResult. Web research does not work in scheduled runs, so the weekly pass will fail loudly too. $detail"
    }
    if (-not $latest) { throw "research check returned 0 but wrote no result file in $logDir" }
    Write-Host "    RESEARCH CHECK PASSED under S4U: $($latest.FullName)"
}

try {
    if ($Unregister -and $CheckResearch) { throw 'Use -Unregister or -CheckResearch, not both.' }
    if (-not $PlanOnly) { Assert-Elevated }
    $scheduler = Get-Scheduler
    if ($PlanOnly) { Show-Plan $scheduler (Get-Layout) }
    elseif ($Unregister) { Unregister-Tasks $scheduler }
    elseif ($CheckResearch) { Invoke-ResearchCheck $scheduler (Get-Layout) }
    else { Register-Tasks $scheduler (Get-Layout) }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
