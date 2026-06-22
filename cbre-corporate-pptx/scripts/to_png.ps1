param(
    [string]$In,
    [string]$OutDir = 'slide_imgs',
    [int]$SlideIndex = 0,           # 1-based; 0 = export all slides (default)
    [int]$Width = 1600,
    [int]$Height = 900
)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$abs = (Resolve-Path $In).Path
$outAbs = (Resolve-Path $OutDir).Path
$pp = New-Object -ComObject PowerPoint.Application
$pres = $pp.Presentations.Open($abs, $true, $true, $false)
if ($SlideIndex -gt 0) {
    # Single-slide export (used by resolve_slide for fast iteration)
    if ($SlideIndex -gt $pres.Slides.Count) {
        $pres.Close()
        $pp.Quit()
        Write-Error "SlideIndex $SlideIndex out of range (deck has $($pres.Slides.Count) slides)."
        exit 1
    }
    $slide = $pres.Slides.Item($SlideIndex)
    $name = "{0:D2}.png" -f $SlideIndex
    $slide.Export((Join-Path $outAbs $name), "PNG", $Width, $Height)
    Write-Output "Exported slide $SlideIndex to $(Join-Path $outAbs $name)"
} else {
    # Whole-deck export (default; backwards compatible).
    # Pre-clean stale PNGs first: if a prior render produced more slides than this one
    # (the deck shrank, or an old full set is still here), leftover NN.png files would
    # make a reviewer inspect slides that no longer exist. Only the whole-deck branch
    # clears the folder; the single-slide branch above deliberately re-renders one PNG
    # into an existing set (used by resolve_slide for fast iteration), so it must NOT.
    Get-ChildItem -Path $outAbs -Filter '*.png' -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    $i = 1
    foreach($slide in $pres.Slides){
        $name = "{0:D2}.png" -f $i
        $slide.Export((Join-Path $outAbs $name), "PNG", $Width, $Height)
        $i++
    }
    Write-Output "Exported $($i-1) slides to $outAbs"
}
$pres.Close()
$pp.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($pres) | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
