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

# ── helper ──────────────────────────────────────────────────────────
function Set-RegString {
    param([string]$Path, [string]$Name, [string]$Value)
    if (-not (Test-Path $Path)) { New-Item -Path $Path -Force | Out-Null }
    # PowerShell requires the literal "(default)" to set a key's default value
    $regName = if ($Name -eq "") { "(default)" } else { $Name }
    Set-ItemProperty -Path $Path -Name $regName -Value $Value -Force
}

# ── uninstall ───────────────────────────────────────────────────────
if ($Uninstall) {
    Write-Host "Removing '$AppName' file association..."
    Remove-Item  "HKCU:\SOFTWARE\Classes\$ProgId"      -Recurse -Force -EA SilentlyContinue
    Remove-Item  "HKCU:\SOFTWARE\Clients\$AppName"     -Recurse -Force -EA SilentlyContinue
    Remove-ItemProperty "HKCU:\SOFTWARE\Classes\.csv\OpenWithProgids" -Name $ProgId -EA SilentlyContinue
    Remove-ItemProperty "HKCU:\SOFTWARE\RegisteredApplications"       -Name $AppName -EA SilentlyContinue
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

# ── build the open command ──────────────────────────────────────────
# cmd /c runs the bat, then the window closes when the TUI quits normally.
# Double-outer-quote is the Windows cmd /c quoting convention for paths with spaces.
$openCmd = 'cmd.exe /c ""{0}" "%1""' -f $LauncherPath

# ── register ProgID ─────────────────────────────────────────────────
Write-Host "Registering ProgID '$ProgId'..."
$base = "HKCU:\SOFTWARE\Classes\$ProgId"
Set-RegString $base                       ""          $AppName
Set-RegString "$base\DefaultIcon"         ""          "$env:SystemRoot\System32\SHELL32.dll,1"
Set-RegString "$base\shell\open"          ""          "Open with $AppName"
Set-RegString "$base\shell\open\command"  ""          $openCmd

# ── add to .csv OpenWithProgids ─────────────────────────────────────
Write-Host "Adding to .csv OpenWithProgids..."
Set-RegString "HKCU:\SOFTWARE\Classes\.csv\OpenWithProgids" $ProgId ""

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
