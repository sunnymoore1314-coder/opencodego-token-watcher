# Capture region at (X,Y) size WxH. Keep pure ASCII (PS5.1 misparses UTF-8 comments).
param([int]$W = 800, [int]$H = 600, [int]$X = 0, [int]$Y = 0, [string]$Out = "$env:TEMP\ui_shot.png")
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = New-Object System.Drawing.Bitmap($W, $H)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($X, $Y, 0, 0, $b.Size)
$b.Save($Out)
$g.Dispose(); $b.Dispose()
Write-Output "saved: $Out"
