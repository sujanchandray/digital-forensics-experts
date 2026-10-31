$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path $root "dist\setup-stage"
$dist = Join-Path $root "dist"
$target = Join-Path $dist "QuickStorageHealthCheck-Setup.exe"
$ico = Join-Path $dist "setup.ico"
$hta = Join-Path $dist "QuickStorageHealthCheck-Setup.hta"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Get-ChildItem -LiteralPath $stage -Force | Remove-Item -Recurse -Force
foreach ($old in @($target, $ico, $hta)) {
    if (Test-Path $old) { Remove-Item -Force $old }
}

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

Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Runtime.InteropServices;
public static class QshcIconCopy {
    const uint LOAD_LIBRARY_AS_DATAFILE = 2;
    delegate bool EnumProc(IntPtr module, IntPtr type, IntPtr name, IntPtr param);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool FreeLibrary(IntPtr module);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr FindResource(IntPtr module, IntPtr name, IntPtr type);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr LoadResource(IntPtr module, IntPtr info);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr LockResource(IntPtr data);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint SizeofResource(IntPtr module, IntPtr info);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool EnumResourceNames(IntPtr module, IntPtr type, EnumProc proc, IntPtr param);
    static int capturedId = -1;
    static bool Capture(IntPtr module, IntPtr type, IntPtr name, IntPtr param) {
        long value = name.ToInt64();
        if ((value & unchecked((long)0xFFFF0000)) == 0) capturedId = (int)(value & 0xFFFF);
        return false;
    }
    public static void CopyFirstGroupIcon(string sourceExe, string destIco) {
        capturedId = -1;
        IntPtr module = LoadLibraryEx(sourceExe, IntPtr.Zero, LOAD_LIBRARY_AS_DATAFILE);
        if (module == IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try {
            if (!EnumResourceNames(module, new IntPtr(14), Capture, IntPtr.Zero) && capturedId < 0)
                throw new InvalidOperationException("No icon group");
            byte[] group = Read(module, new IntPtr(14), new IntPtr(capturedId));
            int count = BitConverter.ToUInt16(group, 4);
            byte[][] images = new byte[count][];
            for (int i = 0; i < count; i++) {
                int entry = 6 + (14 * i);
                ushort id = BitConverter.ToUInt16(group, entry + 12);
                images[i] = Read(module, new IntPtr(3), new IntPtr(id));
            }
            using (var stream = File.Create(destIco))
            using (var writer = new BinaryWriter(stream)) {
                writer.Write((ushort)0);
                writer.Write((ushort)1);
                writer.Write((ushort)count);
                int offset = 6 + (16 * count);
                for (int i = 0; i < count; i++) {
                    int entry = 6 + (14 * i);
                    writer.Write(group[entry]);
                    writer.Write(group[entry + 1]);
                    writer.Write(group[entry + 2]);
                    writer.Write(group[entry + 3]);
                    writer.Write(BitConverter.ToUInt16(group, entry + 4));
                    writer.Write(BitConverter.ToUInt16(group, entry + 6));
                    writer.Write(images[i].Length);
                    writer.Write(offset);
                    offset += images[i].Length;
                }
                for (int i = 0; i < count; i++) writer.Write(images[i]);
            }
        } finally {
            FreeLibrary(module);
        }
    }
    static byte[] Read(IntPtr module, IntPtr type, IntPtr name) {
        IntPtr info = FindResource(module, name, type);
        if (info == IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        IntPtr data = LoadResource(module, info);
        IntPtr locked = LockResource(data);
        uint size = SizeofResource(module, info);
        byte[] bytes = new byte[size];
        Marshal.Copy(locked, bytes, 0, (int)size);
        return bytes;
    }
}
"@

$iconSource = Join-Path $env:SystemRoot "System32\wextract.exe"
[QshcIconCopy]::CopyFirstGroupIcon($iconSource, $ico)

$csc = Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:SystemRoot "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
& $csc /nologo /target:winexe /optimize+ "/win32icon:$ico" "/out:$target" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (Join-Path $root "installer\SetupWindow.cs")
if ($LASTEXITCODE -ne 0) { throw "The setup window did not compile." }

$marker = [Text.Encoding]::ASCII.GetBytes("`r`n###QSHC-PAYLOAD###`r`n")
$tail = [Text.Encoding]::ASCII.GetBytes($wrapped)
$stream = [IO.File]::Open($target, [IO.FileMode]::Append, [IO.FileAccess]::Write)
try {
    $stream.Write($marker, 0, $marker.Length)
    $stream.Write($tail, 0, $tail.Length)
} finally {
    $stream.Close()
}
Remove-Item -Force $zip, $ico
Write-Output $target
Get-Item $target | Select-Object FullName, Length
