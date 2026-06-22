# Bake text-frame autofit into a built deck via PowerPoint COM.
#
# python-pptx writes the autofit element (spAutoFit for "resize shape to fit
# text") but PowerPoint only recomputes the box geometry when a frame is edited,
# not on file open, so a freshly built deck shows boxes that do not fit their
# text until you click into them. This script forces PowerPoint to APPLY the
# autofit on every text frame and saves, so the file is correct on first open.
#
# Anchor-aware, so it never misaligns deliberately-placed slots:
#   * TOP-anchored frames    -> SHAPE_TO_FIT_TEXT (box hugs / contains the text)
#   * MIDDLE/BOTTOM-anchored  -> NONE (kept fixed: table cells, centred headings
#                                keep their slot and carry no lazy-autofit bug)
# Real tables (graphic frames) keep PowerPoint's own row autofit; their cells
# only get word-wrap asserted.
#
# Usage:  powershell -ExecutionPolicy Bypass -File bake_autofit.ps1 -In deck.pptx
param([string]$In)
$ErrorActionPreference = 'Stop'

$abs = (Resolve-Path -LiteralPath $In).Path

# COM enum values (avoids needing the interop assemblies loaded).
$ppAutoSizeNone        = 0
$ppAutoSizeShapeToFit  = 1
$msoAnchorTop          = 1   # MsoVerticalAnchor.msoAnchorTop
$msoTrue               = -1
$msoGroup              = 6   # MsoShapeType.msoGroup

$script:baked = 0
$script:fixed = 0

function Bake-Shape($sh) {
    # Groups: recurse into members.
    $stype = 0
    try { $stype = [int]$sh.Type } catch {}
    if ($stype -eq $msoGroup) {
        foreach ($child in $sh.GroupItems) { Bake-Shape $child }
        return
    }
    # Real PowerPoint tables: leave row autofit to PowerPoint; just assert wrap.
    $hasTable = $false
    try { $hasTable = ($sh.HasTable -eq $msoTrue) } catch {}
    if ($hasTable) {
        try {
            foreach ($row in $sh.Table.Rows) {
                foreach ($cell in $row.Cells) {
                    $ctf = $cell.Shape.TextFrame
                    if ($ctf.HasText -eq $msoTrue) { $ctf.WordWrap = $msoTrue }
                }
            }
        } catch {}
        return
    }
    # Text shapes (textboxes, autoshapes with text).
    $hasTf = $false
    try { $hasTf = ($sh.HasTextFrame -eq $msoTrue) } catch {}
    if (-not $hasTf) { return }
    try {
        $tf = $sh.TextFrame
        if ($tf.HasText -ne $msoTrue) { return }
        $tf.WordWrap = $msoTrue
        $anchor = $msoAnchorTop
        try { $anchor = [int]$tf.VerticalAnchor } catch {}
        if ($anchor -eq $msoAnchorTop) {
            # Toggle None -> ShapeToFitText to force PowerPoint to recompute the
            # box height now and persist it on save.
            $tf.AutoSize = $ppAutoSizeNone
            $tf.AutoSize = $ppAutoSizeShapeToFit
            $script:baked++
        } else {
            # Middle/bottom-anchored slot: pin fixed so the slot and its
            # vertical centring are preserved and there is no lazy-autofit bug.
            $tf.AutoSize = $ppAutoSizeNone
            $script:fixed++
        }
    } catch {}
}

$pp = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly=False, Untitled=False, WithWindow=True).
    # WithWindow MUST be True: opening window-less makes PowerPoint treat the
    # presentation as non-modifiable, so the AutoSize edits silently fail and
    # Save() raises "Presentation cannot be modified". PowerPoint does not allow
    # Application.Visible = False, so minimise the window to keep it unobtrusive.
    $pres = $pp.Presentations.Open($abs, $false, $false, $true)
    try { $pres.Windows.Item(1).WindowState = 2 } catch {}   # 2 = ppWindowMinimized
    foreach ($slide in $pres.Slides) {
        foreach ($sh in $slide.Shapes) { Bake-Shape $sh }
    }
    $pres.Save()
    $pres.Close()
    Write-Output "baked $($script:baked) top-anchored text shapes; pinned $($script:fixed) slot shapes"
} finally {
    $pp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
}
