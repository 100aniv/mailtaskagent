$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "MailTaskAgent virtual environment was not found: $pythonPath"
}

Push-Location $projectRoot
try {
    & $pythonPath -m streamlit run app.py --server.headless true --server.port 8501
    $commandExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $commandExitCode
