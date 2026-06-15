#Requires -Version 5.1
<#
.SYNOPSIS
    Installs / uninstalls CSV Analyzer as a Windows handler for .csv files.

.PARAMETER Uninstall
    Remove all registry entries created by a previous install.

.EXAMPLE
    .\install_csv_default.ps1
    .\install_csv_default.ps1 -Uninstall
#>
param([switch]$Uninstall)

$ProgId       = 'CsvTuiFile'
$AppName      = 'CSV Analyzer'
$ScriptPath   = "$PSScriptRoot\csv_tui.py"
$LauncherPath = "$PSScriptRoot\csv_tui_launcher.bat"
$ExePath      = "$PSScriptRoot\csv_analyzer.exe"

# ── helper ──────────────────────────────────────────────────────────
function Set-RegString {
    param([string]$Path, [string]$Name, [string]$Value)
    if (-not (Test-Path $Path)) { New-Item -Path $Path -Force | Out-Null }
    $regName = if ($Name -eq "") { "(default)" } else { $Name }
    Set-ItemProperty -Path $Path -Name $regName -Value $Value -Force
}

# ── uninstall ───────────────────────────────────────────────────────
if ($Uninstall) {
    Write-Host "Removing '$AppName' file association..."
    Remove-Item  "HKCU:\SOFTWARE\Classes\$ProgId"                               -Recurse -Force -EA SilentlyContinue
    Remove-Item  "HKCU:\SOFTWARE\Clients\$AppName"                              -Recurse -Force -EA SilentlyContinue
    Remove-Item  "HKCU:\SOFTWARE\Classes\Applications\csv_analyzer.exe"         -Recurse -Force -EA SilentlyContinue
    Remove-Item  "HKCU:\SOFTWARE\Classes\Applications\csv_tui_launcher.bat"     -Recurse -Force -EA SilentlyContinue
    Remove-ItemProperty "HKCU:\SOFTWARE\Classes\.csv\OpenWithProgids" -Name $ProgId          -EA SilentlyContinue
    Remove-ItemProperty "HKCU:\SOFTWARE\RegisteredApplications"       -Name $AppName         -EA SilentlyContinue
    Remove-Item  "HKCU:\SOFTWARE\Classes\.csv\OpenWithList\csv_analyzer.exe"    -Recurse -Force -EA SilentlyContinue
    Remove-Item  "HKCU:\SOFTWARE\Classes\.csv\OpenWithList\csv_tui_launcher.bat" -Recurse -Force -EA SilentlyContinue
    if (Test-Path $ExePath) { Remove-Item $ExePath -Force -EA SilentlyContinue }
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

# ── prerequisites ───────────────────────────────────────────────────
$errors = @()
if (-not (Test-Path $ScriptPath))   { $errors += "csv_tui.py not found at: $ScriptPath" }
if (-not (Test-Path $LauncherPath)) { $errors += "csv_tui_launcher.bat not found at: $LauncherPath" }
if (-not (Get-Command python -EA SilentlyContinue)) { $errors += "Python not found in PATH" }
if ($errors) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }

$pythonExe = (Get-Command python).Source
Write-Host "Python : $pythonExe"
Write-Host "Script : $ScriptPath"
Write-Host ""

# ── compile launcher exe ─────────────────────────────────────────────
if (-not (Test-Path $ExePath)) {

    # Find csc.exe (ships with .NET Framework on every Windows 10/11 machine)
    $cscExe = Get-ChildItem "$env:SystemRoot\Microsoft.NET\Framework64" -Filter "csc.exe" -Recurse -EA SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $cscExe) {
        $cscExe = Get-ChildItem "$env:SystemRoot\Microsoft.NET\Framework" -Filter "csc.exe" -Recurse -EA SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    }

    # Generate a simple spreadsheet icon so the exe doesn't show the CMD prompt icon
    $iconPath = "$PSScriptRoot\_csv_analyzer_tmp.ico"
    try {
        Add-Type -AssemblyName System.Drawing -EA Stop

        $size = 32
        $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g   = [System.Drawing.Graphics]::FromImage($bmp)
        $g.Clear([System.Drawing.Color]::Transparent)

        # Background: dark teal/green
        $bg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 0, 105, 92))
        $g.FillRectangle($bg, 1, 1, 30, 30)

        # Header row: slightly lighter
        $hdr = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 0, 137, 123))
        $g.FillRectangle($hdr, 1, 1, 30, 8)

        # Grid lines (white, low opacity)
        $linePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(180, 255, 255, 255), 1)
        $g.DrawLine($linePen, 1,  9, 31,  9)   # below header
        $g.DrawLine($linePen, 1, 17, 31, 17)   # mid row
        $g.DrawLine($linePen, 1, 25, 31, 25)   # bottom row
        $g.DrawLine($linePen, 9,  1,  9, 31)   # left column divider

        # Outer border
        $border = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(220, 255, 255, 255), 1)
        $g.DrawRectangle($border, 1, 1, 29, 29)

        $g.Dispose()

        # Save as PNG-in-ICO (modern format, Vista+)
        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $pngBytes = $ms.ToArray()
        $ms.Close()
        $bmp.Dispose()

        $fs = [System.IO.File]::OpenWrite($iconPath)
        $bw = New-Object System.IO.BinaryWriter($fs)
        $bw.Write([UInt16]0)                       # reserved
        $bw.Write([UInt16]1)                       # type = 1 (ICO)
        $bw.Write([UInt16]1)                       # image count
        $bw.Write([Byte]$size)                     # width
        $bw.Write([Byte]$size)                     # height
        $bw.Write([Byte]0)                         # color count (0 = 256+)
        $bw.Write([Byte]0)                         # reserved
        $bw.Write([UInt16]1)                       # planes
        $bw.Write([UInt16]32)                      # bit depth
        $bw.Write([UInt32]$pngBytes.Length)        # image data size
        $bw.Write([UInt32]22)                      # image data offset (6 + 16)
        $bw.Write($pngBytes)
        $bw.Close()
        $fs.Close()
        Write-Host "Icon    : generated"
    } catch {
        Write-Warning "Could not generate icon ($_) - exe will use default icon"
        $iconPath = $null
    }

    # C# source for the launcher stub
    $csharp = @'
using System;
using System.Diagnostics;
using System.IO;
class CsvAnalyzer {
    static void Main(string[] args) {
        string dir = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
        string bat = Path.Combine(dir, "csv_tui_launcher.bat");
        string cmdArgs = args.Length > 0
            ? "/c \"\"" + bat + "\" \"" + args[0] + "\"\""
            : "/c \"\"" + bat + "\"\"";
        var p = Process.Start("cmd.exe", cmdArgs);
        if (p != null) p.WaitForExit();
    }
}
'@

    Write-Host "Compiling csv_analyzer.exe..."

    if ($cscExe) {
        # Compile via csc.exe so we can embed the icon
        $srcPath = "$PSScriptRoot\_csv_analyzer_stub.cs"
        [System.IO.File]::WriteAllText($srcPath, $csharp, [System.Text.Encoding]::UTF8)

        $cscArgs = @("/nologo", "/out:$ExePath", "/t:exe")
        if ($iconPath -and (Test-Path $iconPath)) { $cscArgs += "/win32icon:$iconPath" }
        $cscArgs += $srcPath

        & $cscExe @cscArgs | Out-Null
        Remove-Item $srcPath -Force -EA SilentlyContinue
    } else {
        # Fallback: Add-Type (no custom icon, but functional)
        Write-Warning "csc.exe not found - compiling without custom icon"
        Add-Type -TypeDefinition $csharp -OutputAssembly $ExePath -OutputType ConsoleApplication
    }

    if ($iconPath -and (Test-Path $iconPath)) { Remove-Item $iconPath -Force -EA SilentlyContinue }

    if (Test-Path $ExePath) {
        Write-Host "Compiled : $ExePath" -ForegroundColor Green
    } else {
        Write-Error "Compilation failed. Check that .NET Framework is installed."
        exit 1
    }
} else {
    Write-Host "Launcher : $ExePath (already exists, delete it to recompile)"
}
Write-Host ""

# ── build open command ──────────────────────────────────────────────
$exeOpenCmd = '"' + $ExePath + '" "%1"'

# ── register ProgID ─────────────────────────────────────────────────
Write-Host "Registering ProgID '$ProgId'..."
$base = "HKCU:\SOFTWARE\Classes\$ProgId"
Set-RegString $base                       ""          $AppName
Set-RegString "$base\DefaultIcon"         ""          "$ExePath,0"
Set-RegString "$base\shell\open"          ""          "Open with $AppName"
Set-RegString "$base\shell\open\command"  ""          $exeOpenCmd

# ── register under Applications (required for "Open With" dialog) ───
Write-Host "Registering under Applications..."
$appKey = "HKCU:\SOFTWARE\Classes\Applications\csv_analyzer.exe"
Set-RegString $appKey                        "FriendlyAppName"  $AppName
Set-RegString "$appKey\shell\open"           ""                 "Open with $AppName"
Set-RegString "$appKey\shell\open\command"   ""                 $exeOpenCmd
Set-RegString "$appKey\SupportedTypes"       ".csv"             ""

# ── add to .csv Open With lists ──────────────────────────────────────
Write-Host "Adding to .csv OpenWith lists..."
Set-RegString "HKCU:\SOFTWARE\Classes\.csv\OpenWithProgids"               $ProgId            ""
Set-RegString "HKCU:\SOFTWARE\Classes\.csv\OpenWithList\csv_analyzer.exe" ""                 ""

# ── register app capabilities (shows in Settings > Default Apps) ────
Write-Host "Registering app capabilities..."
$cap = "HKCU:\SOFTWARE\Clients\$AppName\Capabilities"
Set-RegString $cap                        "ApplicationName"        $AppName
Set-RegString $cap                        "ApplicationDescription" "Terminal UI for browsing and analysing CSV files"
Set-RegString "$cap\FileAssociations"     ".csv"                   $ProgId
Set-RegString "HKCU:\SOFTWARE\RegisteredApplications" `
              $AppName  "SOFTWARE\Clients\$AppName\Capabilities"

# ── notify Windows shell of changes ────────────────────────────────
$src = @'
using System;
using System.Runtime.InteropServices;
public class ShellNotify {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int wEventId, int uFlags, IntPtr dwItem1, IntPtr dwItem2);
}
'@
try {
    Add-Type -TypeDefinition $src -EA Stop
    [ShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
} catch {}

# ── done ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Registered '$AppName' as a handler for .csv files." -ForegroundColor Green
Write-Host ""
Write-Host "ONE-TIME STEP - set as default (Windows blocks this programmatically):" -ForegroundColor Yellow
Write-Host "  1. Right-click any .csv file in File Explorer"
Write-Host "  2. Open with  >  Choose another app"
Write-Host "  3. Select '$AppName'"
Write-Host "  4. Tick 'Always use this app to open .csv files'"
Write-Host "  5. Click OK"
Write-Host ""
Write-Host "Alternative: Settings > Apps > Default apps > search 'csv'" -ForegroundColor Cyan
