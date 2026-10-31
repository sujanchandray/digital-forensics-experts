$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path $root "dist\setup-stage"
$dist = Join-Path $root "dist"
$target = Join-Path $dist "QuickStorageHealthCheck-Setup.exe"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
if (Test-Path $target) { Remove-Item -Force $target }

Copy-Item -Force (Join-Path $root "StorageHealthCheck-Setup.cmd") $stage
Copy-Item -Force (Join-Path $root "installer\Install-StorageHealthCheck.ps1") $stage
Copy-Item -Force (Join-Path $root "ssd_health.py") $stage
Copy-Item -Force (Join-Path $root "tools\smartctl.exe") $stage
Copy-Item -Force (Join-Path $root "tools\COPYING.txt") $stage

$files = @(
    "StorageHealthCheck-Setup.cmd",
    "Install-StorageHealthCheck.ps1",
    "ssd_health.py",
    "smartctl.exe",
    "COPYING.txt"
)
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("[Version]")
$lines.Add("Class=IEXPRESS")
$lines.Add("SEDVersion=3")
$lines.Add("[Options]")
$lines.Add("PackagePurpose=InstallApp")
$lines.Add("ShowInstallProgramWindow=1")
$lines.Add("HideExtractAnimation=1")
$lines.Add("UseLongFileName=1")
$lines.Add("InsideCompressed=0")
$lines.Add("CAB_FixedSize=0")
$lines.Add("CAB_ResvCodeSigning=0")
$lines.Add("RebootMode=0")
$lines.Add("InstallPrompt=%InstallPrompt%")
$lines.Add("DisplayLicense=%DisplayLicense%")
$lines.Add("FinishMessage=%FinishMessage%")
$lines.Add("TargetName=%TargetName%")
$lines.Add("FriendlyName=%FriendlyName%")
$lines.Add("AppLaunched=%AppLaunched%")
$lines.Add("PostInstallCmd=%PostInstallCmd%")
$lines.Add("AdminQuietInstCmd=%AdminQuietInstCmd%")
$lines.Add("UserQuietInstCmd=%UserQuietInstCmd%")
$lines.Add("SourceFiles=SourceFiles")
$lines.Add("[Strings]")
$lines.Add("InstallPrompt=")
$lines.Add("DisplayLicense=")
$lines.Add("FinishMessage=")
$lines.Add("TargetName=$target")
$lines.Add("FriendlyName=QuickStorageHealthCheck")
$lines.Add("AppLaunched=cmd.exe /c StorageHealthCheck-Setup.cmd")
$lines.Add("PostInstallCmd=<None>")
$lines.Add("AdminQuietInstCmd=")
$lines.Add("UserQuietInstCmd=")
for ($i = 0; $i -lt $files.Count; $i++) {
    $lines.Add(('FILE{0}="{1}"' -f $i, $files[$i]))
}
$lines.Add("[SourceFiles]")
$lines.Add("SourceFiles0=$stage\")
$lines.Add("[SourceFiles0]")
for ($i = 0; $i -lt $files.Count; $i++) {
    $lines.Add(('%FILE{0}%=' -f $i))
}
$sed = Join-Path $dist "QuickStorageHealthCheck.sed"
Set-Content -Path $sed -Value $lines -Encoding ASCII
$iexpress = Join-Path $env:SystemRoot "System32\iexpress.exe"
$proc = Start-Process -FilePath $iexpress -ArgumentList @("/N", $sed) -Wait -PassThru
Write-Output "iexpress-exit=$($proc.ExitCode)"
if (-not (Test-Path $target)) {
    throw "IExpress did not write $target"
}
Write-Output $target
Get-Item $target | Select-Object FullName, Length
