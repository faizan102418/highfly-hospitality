$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$tenancyPath = Join-Path $repo 'apps\api\app\tenancy.py'
$mainPath = Join-Path $repo 'apps\api\app\main.py'
$configPath = Join-Path $repo 'apps\api\app\configuration.py'
$testPath = Join-Path $repo 'apps\api\tests\test_configuration_api.py'

if (!(Test-Path $tenancyPath) -or !(Test-Path $mainPath)) {
    throw 'Run this script from the root of the la-serene-hms repository.'
}
if (Test-Path $configPath) { throw 'configuration.py already exists; inspect the existing implementation before applying this patch.' }
if ((git status --short) -and $env:HMS_ALLOW_DIRTY -ne '1') {
    throw 'Working tree has local changes. Commit/stash them first, or set HMS_ALLOW_DIRTY=1 after reviewing them.'
}

# The zip includes the new API module and test. Copy them into the expected paths.
Copy-Item (Join-Path $PSScriptRoot 'apps\api\app\configuration.py') $configPath
Copy-Item (Join-Path $PSScriptRoot 'apps\api\tests\test_configuration_api.py') $testPath

$tenancy = Get-Content $tenancyPath -Raw
if ($tenancy -notmatch 'class OrganizationSetting\(') {
    $tenancy = $tenancy.Replace('from sqlalchemy import Boolean, ForeignKey, String, Text', 'from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint')
    $modelText = Get-Content (Join-Path $PSScriptRoot 'apps\api\app\configuration_models.txt') -Raw
    Set-Content -Path $tenancyPath -Value ($tenancy.TrimEnd() + "`r`n" + $modelText + "`r`n") -Encoding utf8
}

$main = Get-Content $mainPath -Raw
if ($main -notmatch 'from \.configuration import router as configuration_router') {
    $anchor = 'from .config import settings'
    # main.py has no config import in this codebase, so place router import beside other local router imports.
    $anchor = 'from .billing import router as billing_router'
    if (!$main.Contains($anchor)) { throw 'Could not find a stable router-import insertion point in main.py.' }
    $main = $main.Replace($anchor, 'from .configuration import router as configuration_router' + "`r`n" + $anchor)
    $routerAnchor = 'app.include_router(billing_router)'
    if (!$main.Contains($routerAnchor)) { throw 'Could not find router registration insertion point in main.py.' }
    $main = $main.Replace($routerAnchor, 'app.include_router(configuration_router)' + "`r`n" + $routerAnchor)
    Set-Content -Path $mainPath -Value $main -Encoding utf8
}

Write-Host 'Configuration API patch applied. Review the diff, then run tests.' -ForegroundColor Green
Write-Host 'Suggested commands:'
Write-Host '  git diff --check'
Write-Host '  cd apps\api'
Write-Host '  python -m pytest tests/test_configuration_api.py tests/test_auth_security.py tests/test_router_registration.py -q'
Write-Host '  python -m pytest -q'
