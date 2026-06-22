param([string]$In, [string]$Out)
$abs = (Resolve-Path $In).Path
if (-not $Out) {
    # Default the output PDF next to the input, same base name.
    $Out = [System.IO.Path]::ChangeExtension($abs, '.pdf')
}
# Resolve to an absolute path so SaveAs doesn't depend on the current directory.
if (-not [System.IO.Path]::IsPathRooted($Out)) {
    $Out = Join-Path (Get-Location).Path $Out
}
$pp = New-Object -ComObject PowerPoint.Application
$pres = $pp.Presentations.Open($abs, $true, $true, $false)
$pres.SaveAs($Out, 32)  # 32 = PDF
$pres.Close()
$pp.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($pres) | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
Write-Output "DONE: $Out"
