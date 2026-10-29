# Uses an existing Python only. Does not install dependencies or alter benchmark configuration.
$ErrorActionPreference = 'Stop'
$factoryRoot = Split-Path -Parent $PSScriptRoot
$factoryPython = $env:STEM_FACTORY_PYTHON
if (-not $factoryPython) {
    $foundPython = Get-Command python -ErrorAction SilentlyContinue
    if ($foundPython) { $factoryPython = $foundPython.Source }
}
if (-not $factoryPython) {
    $candidatePython = Join-Path $env:LOCALAPPDATA 'Temp\calculate-average-python313\python.exe'
    if (Test-Path -LiteralPath $candidatePython) { $factoryPython = $candidatePython }
}
if (-not $factoryPython) { throw 'Set STEM_FACTORY_PYTHON to an existing Python 3.11+ executable.' }
$env:STEM_FACTORY_ROOT = $factoryRoot
Push-Location -LiteralPath $factoryRoot
try {
    # Supports the existing embedded runtime without editing its ._pth file.
    $entry = "import os,sys; sys.path.insert(0,os.environ['STEM_FACTORY_ROOT']); from stem_factory.cli import main; raise SystemExit(main())"
    & $factoryPython -B -c $entry @args
    $factoryExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $factoryExit
