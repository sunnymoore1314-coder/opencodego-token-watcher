# Crop top-left region and scale 2x, save as PNG. Pure ASCII only.
param([string]$In = "$env:TEMP\ui_shot.png", [string]$Out = "$env:TEMP\ui_crop.png")
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Image]::FromFile($In)
$w = 300; $h = 200
$b = New-Object System.Drawing.Bitmap(($w * 2), ($h * 2))
$g = [System.Drawing.Graphics]::FromImage($b)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$g.DrawImage($src, (New-Object System.Drawing.Rectangle(0, 0, ($w * 2), ($h * 2))),
             (New-Object System.Drawing.Rectangle(0, 0, $w, $h)),
             [System.Drawing.GraphicsUnit]::Pixel)
$b.Save($Out)
$g.Dispose(); $b.Dispose(); $src.Dispose()
Write-Output "saved: $Out"
