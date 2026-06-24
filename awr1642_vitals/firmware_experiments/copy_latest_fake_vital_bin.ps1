$ErrorActionPreference = 'Stop'

$source = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\..\..\ccs_workspace_awr1642_vital_phase\AWR16xx_mss_nonOS\Debug\xwr16xx_mmw_nonOS.bin')
)
$destinationDirectory = Join-Path $PSScriptRoot 'built_bins'
$destination = Join-Path $destinationDirectory 'awr1642_nonos_fake_vital_phase_0xFE01.bin'

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Built firmware binary not found: $source"
}

New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $destination -Force

$copied = Get-Item -LiteralPath $destination
Write-Host "Copied firmware binary to: $($copied.FullName)"
Write-Host "Total bytes: $($copied.Length)"
Write-Warning 'Binary copied only. No hardware flashing was performed.'
