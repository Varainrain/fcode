# EREBUS arena worker -> always-on Scheduled Task on a Windows VPS.
# Run from the fcode repo root (elevated PowerShell):
#   powershell -ExecutionPolicy Bypass -File deploy\vps-setup.ps1 -Url https://warroom-hq.vercel.app -Key <WARROOM_KEY>
param(
  [Parameter(Mandatory=$true)][string]$Url,
  [Parameter(Mandatory=$true)][string]$Key
)
$ErrorActionPreference = "Stop"
$repo = (Get-Location).Path

if (-not (Test-Path "$repo\warroom_worker.py") -or -not (Test-Path "$repo\bots")) {
  throw "Run this from the fcode repo root (needs warroom_worker.py + bots\ + maps\). You are in $repo"
}
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
  throw "Python not found. Install it first:  winget install Python.Python.3.12  (or from python.org, tick 'Add to PATH'), then reopen PowerShell."
}

Write-Host "== installing fcode engine ==" -ForegroundColor Cyan
& python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ fcode==2.3.0.dev26

Write-Host "== storing config (machine env vars) ==" -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("WARROOM_URL", $Url, "Machine")
[Environment]::SetEnvironmentVariable("WARROOM_KEY", $Key, "Machine")
[Environment]::SetEnvironmentVariable("WARROOM_NAME", "vps", "Machine")

# wrapper: cd to repo, run worker (reads env), append to worker.log
$wrapper = "$repo\_run_worker.cmd"
@"
@echo off
cd /d "$repo"
python -u warroom_worker.py >> "$repo\worker.log" 2>&1
"@ | Set-Content -Encoding ASCII $wrapper

Write-Host "== installing scheduled task 'WarroomWorker' ==" -ForegroundColor Cyan
$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$wrapper`""
$trigger   = New-ScheduledTaskTrigger -AtStartup
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 `
              -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "WarroomWorker" -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "WarroomWorker"

Write-Host ""
Write-Host "== done. worker runs 24/7, starts at boot, restarts on crash ==" -ForegroundColor Green
Write-Host "  live log:  Get-Content '$repo\worker.log' -Wait -Tail 20"
Write-Host "  stop:      Stop-ScheduledTask -TaskName WarroomWorker"
Write-Host "  restart:   Restart-ScheduledTask -TaskName WarroomWorker"
