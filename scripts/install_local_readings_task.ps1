param(
  [string]$TaskName = "Paper Radar Local Readings",
  [string]$Time = "16:35",
  [string]$LibraryDir = "D:\OneDrive - The Chinese University of Hong Kong\Paper_Radar",
  [string]$Python = "D:\Users\plzhu\anaconda3\envs\pet\python.exe",
  [switch]$NoOpenAI
)

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
$Updater = Join-Path $PSScriptRoot "update_local_readings.ps1"

if (-not (Test-Path $Updater)) {
  throw "Cannot find updater script: $Updater"
}

$runAt = [datetime]::ParseExact($Time, "HH:mm", $null)
$arguments = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$Updater`"",
  "-LibraryDir", "`"$LibraryDir`"",
  "-Python", "`"$Python`""
)
if ($NoOpenAI) {
  $arguments += "-NoOpenAI"
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument ($arguments -join " ") `
  -WorkingDirectory $RepoDir
$trigger = New-ScheduledTaskTrigger -Daily -At $runAt
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Scan local Paper_Radar PDFs, publish new reading notes, and refresh the GitHub Pages site." `
  -Force | Out-Null

Write-Output "Installed scheduled task '$TaskName' at $Time."
