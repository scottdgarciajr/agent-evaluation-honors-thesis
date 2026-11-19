param(
    [ValidateSet('Test', 'Live', 'Results', 'GUI')][string]$Mode = 'Test',
    [switch]$NoOpen,
    [switch]$SkipChecks,
    [string]$Model,
    [double]$InputPrice = 0,
    [double]$OutputPrice = 0,
    [double]$Budget = 5
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
$latestPath = Join-Path $projectDirectory 'output\latest-results.json'
$temporaryKey = $false

function Invoke-Python {
    param([string[]]$Arguments)
    & $pythonPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE): $($Arguments -join ' ')" }
}

Push-Location -LiteralPath $projectDirectory
try {
    if ($Mode -eq 'Results') {
        if (-not (Test-Path -LiteralPath $latestPath)) { throw 'No results yet. Run Run Test Evaluation.cmd first.' }
        $latest = Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json
        $reportPath = Join-Path $projectDirectory $latest.report
        if (-not (Test-Path -LiteralPath $reportPath)) { throw 'Latest report is missing. Run the test evaluation again.' }
        Write-Host "Results: $reportPath"
        if (-not $NoOpen) { Invoke-Item -LiteralPath $reportPath }
        exit 0
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host 'Creating the Python 3.12 environment...'
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.12 -m venv .venv
        } else {
            & python -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 and rerun this launcher.' }
        Invoke-Python -Arguments @('-c', "import sys; assert sys.version_info[:2] == (3, 12), 'Python 3.12 is required'")
        Invoke-Python -Arguments @('-m', 'pip', 'install', '-r', 'requirements-lock.txt')
        Invoke-Python -Arguments @('-m', 'pip', 'install', '--no-deps', '-e', '.')
    } else {
        # Recover interrupted setup or a virtual environment created without this package.
        & $pythonPath -c "import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in ['agent_eval', 'agentdojo', 'pytest', 'matplotlib', 'ruff']) else 1)"
        if ($LASTEXITCODE -ne 0) {
            Invoke-Python -Arguments @('-m', 'pip', 'install', '-r', 'requirements-lock.txt')
            Invoke-Python -Arguments @('-m', 'pip', 'install', '--no-deps', '-e', '.')
        }
    }
    if ($Mode -eq 'GUI') {
        $pythonWindowless = Join-Path $projectDirectory '.venv\Scripts\pythonw.exe'
        Start-Process -FilePath $pythonWindowless -ArgumentList @('-m', 'agent_eval.gui') -WorkingDirectory $projectDirectory
        exit 0
    }
    $runName = 'test-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    if ($Mode -eq 'Live') { $runName = $runName.Replace('test-', 'pilot-') }
    $runRelative = 'runs/' + $runName
    $runDirectory = Join-Path $projectDirectory $runRelative
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    Invoke-Python -Arguments @('-m', 'agent_eval.cli', 'doctor')
    Invoke-Python -Arguments @('-m', 'agent_eval.cli', 'validate', '--config', 'configs/pilot.json')
    if ($Mode -eq 'Test') {
        Write-Host 'Running an OFFLINE test evaluation. No model API calls will be made.' -ForegroundColor Cyan
        if (-not $SkipChecks) {
            Invoke-Python -Arguments @('-m', 'ruff', 'check', 'src', 'tests', 'scripts')
            Invoke-Python -Arguments @('-m', 'pip', 'check')
            Invoke-Python -Arguments @('-m', 'pytest', '-q', "--junitxml=$runDirectory/checks.xml")
            Write-Host 'Checking attack payload compatibility (this can take about a minute)...'
            Invoke-Python -Arguments @('scripts/preflight_payloads.py')
        }
        Invoke-Python -Arguments @('-m', 'agent_eval.cli', 'demo', '--output', $runRelative)
    } else {
        Write-Host 'This runs a PAID model pilot. Supply a model and its current verified token prices.' -ForegroundColor Yellow
        if (-not $Model) { $Model = Read-Host 'OpenAI model snapshot ID' }
        if ($InputPrice -le 0) { $InputPrice = [double](Read-Host 'Input USD per million tokens') }
        if ($OutputPrice -le 0) { $OutputPrice = [double](Read-Host 'Output USD per million tokens') }
        if ($InputPrice -le 0 -or $OutputPrice -le 0 -or $Budget -le 0 -or -not $Model) { throw 'Model, positive prices and budget are required.' }
        if (-not $env:OPENAI_API_KEY) {
            $secureKey = Read-Host 'OpenAI API key (hidden; kept only for this process)' -AsSecureString
            $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
            try { $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer) }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }
            $temporaryKey = $true
        }
        Write-Host "Running up to 54 episodes, with an estimated budget cap of USD $Budget."
        $culture = [Globalization.CultureInfo]::InvariantCulture
        Invoke-Python -Arguments @('-m', 'agent_eval.cli', 'run', '--live', '--config', 'configs/pilot.json',
            '--output', $runRelative, '--model', $Model, '--max-cost-usd', $Budget.ToString($culture),
            '--input-usd-per-million', $InputPrice.ToString($culture), '--output-usd-per-million', $OutputPrice.ToString($culture))
    }
    Invoke-Python -Arguments @('-m', 'agent_eval.cli', 'analyze', $runRelative)
    $evaluation = Get-Content -LiteralPath (Join-Path $runDirectory 'analysis\results.json') -Raw | ConvertFrom-Json
    if ($Mode -eq 'Test' -and $evaluation.coverage.completed -ne $evaluation.coverage.scheduled) {
        throw "Some offline episodes failed. Inspect $runDirectory\analysis\report.html"
    }
    $reportRelative = $runRelative + '/analysis/report.html'
    New-Item -ItemType Directory -Path (Split-Path -Parent $latestPath) -Force | Out-Null
    @{ report = $reportRelative; run = $runRelative; mode = $Mode } | ConvertTo-Json | Set-Content -LiteralPath $latestPath -Encoding UTF8
    Write-Host "Finished. Results: $(Join-Path $projectDirectory $reportRelative)" -ForegroundColor Green
    Write-Host 'Use View Results.cmd to reopen this report.'
    if (-not $NoOpen) { Invoke-Item -LiteralPath (Join-Path $projectDirectory $reportRelative) }
} catch {
    Write-Host "Evaluation stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($temporaryKey) { Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue }
    Pop-Location
}
