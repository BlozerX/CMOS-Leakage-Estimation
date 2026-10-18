param([ValidateSet('milestone','characterize','train','circuits','diagnostics','report','all')][string]$Stage = 'all')
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = if ($env:LEAKAGE_PYTHON) { $env:LEAKAGE_PYTHON } else { Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
$env:PYTHONPATH = "$taskRoot\src;$taskRoot\tools\python-packages"
Push-Location -LiteralPath $taskRoot
try {
    if ($Stage -eq 'all') {
        foreach ($taskStage in @('milestone','characterize','train','circuits','diagnostics','report')) {
            & $taskPython -m "leakage.$taskStage"
            if ($LASTEXITCODE -ne 0) { throw "Stage $taskStage failed." }
        }
    } else {
        & $taskPython -m "leakage.$Stage"
        if ($LASTEXITCODE -ne 0) { throw "Stage $Stage failed." }
    }
} finally { Pop-Location }
