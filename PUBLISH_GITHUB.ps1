# OpyT 50+ MVP: safe upload into existing GitHub repo (non-destructive, fast-forward only).
$ErrorActionPreference = 'Stop'
$repoUrl = 'https://github.com/Arromanov1985/opyt50-platform.git'
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$workDir = Join-Path $env:TEMP ('opytno-upload-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))

Write-Host '1/4 Cloning the existing repository...'
git clone $repoUrl $workDir
if ($LASTEXITCODE -ne 0) { throw 'Git clone failed. Check Git installation and GitHub access.' }

Write-Host '2/4 Copying source files...'
$skip = @('.git', '.venv', '.env', '.pytest_cache', 'data', '__pycache__')
Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
    if ($skip -notcontains $_.Name) {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $workDir $_.Name) -Recurse -Force
    }
}

Write-Host '3/4 Creating a commit...'
git -C $workDir add -A
if ($LASTEXITCODE -ne 0) { throw 'Git add failed.' }
$changeCount = @(git -C $workDir status --porcelain).Count
if ($changeCount -eq 0) { Write-Host 'Nothing changed; repository is up to date.'; exit 0 }
git -C $workDir commit -m 'feat: Timeweb-ready OpyT 50+ preview MVP'
if ($LASTEXITCODE -ne 0) { throw 'Git commit failed. Check configured Git name/email.' }

Write-Host '4/4 Pushing to GitHub...'
git -C $workDir push origin main
if ($LASTEXITCODE -ne 0) { throw 'Git push failed. No remote history was overwritten.' }
Write-Host 'Success! https://github.com/Arromanov1985/opyt50-platform'
Write-Host 'Next: Timeweb Cloud -> App Platform -> Dockerfile -> connect GitHub account -> choose main.'
