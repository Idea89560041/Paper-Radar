param(
  [string]$LibraryDir = "D:\OneDrive - The Chinese University of Hong Kong\Paper_Radar",
  [string]$Python = "D:\Users\plzhu\anaconda3\envs\pet\python.exe",
  [switch]$NoOpenAI
)

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
Set-Location $RepoDir

git pull --rebase origin main

$args = @("local_paper_column.py", "--library-dir", $LibraryDir)
if ($NoOpenAI) {
  $args += "--no-openai"
}

& $Python @args
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

git add data/local_readings.json data/local_library_state.json data/reading_assets
if (git diff --cached --quiet) {
  Write-Output "No new local reading notes to publish."
  exit 0
}

git commit -m "Update local reading notes"
git push origin main
