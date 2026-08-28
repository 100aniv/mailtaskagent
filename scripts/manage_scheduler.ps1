param(
    [ValidateSet("Preview", "Install", "Remove")]
    [string]$Mode = "Preview",

    [ValidateRange(1, 60)]
    [int]$IntervalMinutes = 10,

    [string]$TaskName = "MailTaskAgent-GmailSync"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$syncScript = Join-Path $PSScriptRoot "run_gmail_sync.ps1"
$powershellPath = (Get-Command powershell.exe).Source
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$syncScript`""

if (-not (Test-Path -LiteralPath $syncScript)) {
    throw "Gmail sync script was not found: $syncScript"
}

if ($Mode -eq "Preview") {
    [pscustomobject]@{
        Mode = $Mode
        TaskName = $TaskName
        IntervalMinutes = $IntervalMinutes
        Execute = $powershellPath
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
    -Execute $powershellPath `
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
