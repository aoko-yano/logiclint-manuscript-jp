# logiclint runner (Docker)

param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$toolRoot = (Resolve-Path $PSScriptRoot).Path
$workRoot = (Resolve-Path (Get-Location)).Path

Write-Host "Building logiclint Docker image..."
docker build -t logiclint-tool -f "$toolRoot/Dockerfile" "$toolRoot"

Write-Host "Running logiclint (workdir: $workRoot)..."
docker run --rm -v "${workRoot}:/work" -w /work logiclint-tool @Args

