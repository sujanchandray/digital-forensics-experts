$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path $root "dist\setup-stage"
$dist = Join-Path $root "dist"
$target = Join-Path $dist "QuickStorageHealthCheck-Setup.hta"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Get-ChildItem -LiteralPath $stage -Force | Remove-Item -Recurse -Force
if (Test-Path $target) { Remove-Item -Force $target }

Copy-Item -Force (Join-Path $root "installer\Install-StorageHealthCheck.ps1") $stage
Copy-Item -Force (Join-Path $root "installer\Run-QuietSetup.ps1") $stage
Copy-Item -Force (Join-Path $root "ssd_health.py") $stage
Copy-Item -Force (Join-Path $root "tools\smartctl.exe") $stage
Copy-Item -Force (Join-Path $root "tools\COPYING.txt") $stage

$zip = Join-Path $dist "setup-payload.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
$payload = [Convert]::ToBase64String([IO.File]::ReadAllBytes($zip))
$wrapped = [regex]::Replace($payload, ".{76}", "$&`r`n")

$extract = @'
$ErrorActionPreference = "Stop"
$src = $env:QSHC_SRC
$raw = [IO.File]::ReadAllText($src)
$mark = "###QSHC-PAYLOAD###"
$i = $raw.LastIndexOf($mark)
if ($i -lt 0) { exit 1 }
$b64 = ($raw.Substring($i + $mark.Length) -replace "\s","")
$bytes = [Convert]::FromBase64String($b64)
$dest = Join-Path $env:TEMP ("QuickStorageHealthCheck-" + [guid]::NewGuid().ToString("n"))
[void](New-Item -ItemType Directory -Force -Path $dest)
$zip = Join-Path $dest "payload.zip"
[IO.File]::WriteAllBytes($zip, $bytes)
Expand-Archive -Force -Path $zip -DestinationPath $dest
foreach ($f in (Get-ChildItem -LiteralPath $dest -File)) { Unblock-File -LiteralPath $f.FullName -ErrorAction SilentlyContinue }
& (Join-Path $dest "Run-QuietSetup.ps1")
if (-not $?) { exit 1 }
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($extract))

$header = @"
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="x-ua-compatible" content="IE=11">
<title>QuickStorageHealthCheck</title>
<HTA:APPLICATION ID="qshc" APPLICATIONNAME="QuickStorageHealthCheck" BORDER="none" CAPTION="no" SHOWINTASKBAR="yes" SINGLEINSTANCE="yes" SCROLL="no" SYSMENU="no" />
<style>
html, body { margin: 0; height: 100%; background: #07080a; color: #f4f1ea; font-family: "Segoe UI", sans-serif; }
body { display: flex; align-items: center; justify-content: center; }
.card { text-align: center; }
.spin { width: 54px; height: 54px; margin: 0 auto 18px; border-radius: 50%; border: 3px solid rgba(244,241,234,0.16); border-top-color: #d6ff4a; animation: turn 0.8s linear infinite; }
@keyframes turn { to { transform: rotate(360deg); } }
p { margin: 0; letter-spacing: 0.02em; }
.fail { color: #ffb4a8; }
</style>
<script language="JScript">
function htaPath() {
  var path = String(document.location.pathname);
  if (path.charAt(0) === "/") path = path.substring(1);
  return unescape(path);
}
function start() {
  window.resizeTo(380, 220);
  window.moveTo((screen.availWidth - 380) / 2, (screen.availHeight - 220) / 2);
  var sh = new ActiveXObject("WScript.Shell");
  var env = sh.Environment("Process");
  env.Item("QSHC_SRC") = htaPath();
  var code = sh.Run("powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand $encoded", 0, true);
  if (code === 0) {
    window.close();
  } else {
    document.getElementById("spin").style.display = "none";
    var msg = document.getElementById("msg");
    msg.className = "fail";
    msg.innerText = "Setup did not finish. Approve the administrator prompt and run the setup again.";
  }
}
</script>
</head>
<body onload="start()">
<div class="card">
  <div class="spin" id="spin"></div>
  <p id="msg">Preparing the report</p>
</div>
</body>
</html>
###QSHC-PAYLOAD###
"@

Set-Content -Path $target -Value ($header.TrimEnd() + "`r`n" + $wrapped) -Encoding UTF8
Remove-Item -Force $zip
Write-Output $target
Get-Item $target | Select-Object FullName, Length
