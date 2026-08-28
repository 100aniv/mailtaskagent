param(
    [ValidateSet("Preview", "Install", "Remove")]
    [string]$Mode = "Preview",

    [ValidateRange(1, 60)]
    [int]$IntervalMinutes = 1,

    [string]$TaskName = "MailTaskAgent-GmailSync"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonwPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$arguments = "-m mailtaskagent.operations_cli sync-gmail"

if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw "MailTaskAgent windowless Python executable was not found: $pythonwPath"
}

if ($Mode -eq "Preview") {
    [pscustomobject]@{
        Mode = $Mode
        TaskName = $TaskName
        IntervalMinutes = $IntervalMinutes
        Execute = $pythonwPath
        Arguments = $arguments
        WorkingDirectory = $projectRoot
    }
    exit 0
}

if ($Mode -eq "Remove") {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute $pythonwPath `
    -Argument $arguments `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "MailTaskAgent restricted Gmail read-only synchronization" `
    -Force | Out-Null
