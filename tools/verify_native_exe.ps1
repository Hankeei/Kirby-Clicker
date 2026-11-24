param([string]$Exe = (Join-Path $PSScriptRoot '..\dist\KirbyClicker.exe'))
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$Exe = (Resolve-Path -LiteralPath $Exe).Path
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeTestWindow {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left,Top,Right,Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int X,Y; }
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hwnd, ref Point point);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", EntryPoint="GetWindowLongPtrW")] public static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
}
'@
$savedPath = $env:PATH
$savedData = $env:KIRBYCLICKER_DATA
$savedOutput = $env:KIRBYCLICKER_SELFTEST_OUT
$savedStartup = $env:KIRBYCLICKER_STARTUP_OUT
$process = $null
$build = Join-Path $root 'build'
$data = Join-Path $build ('native-gui-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $data -Force | Out-Null
# Quiet test startup. The self-test explicitly verifies music separately.
'{"music_enabled":false}' | Set-Content -LiteralPath (Join-Path $data 'settings.json')
function Find-Button([string]$name) {
    return $script:window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.AndCondition(
            (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Button)),
            (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)))))
}
function Click-Button([string]$name) {
    $button = Find-Button $name
    if (-not $button) { throw "Missing native button: $name" }
    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Start-Sleep -Milliseconds 350
    Write-Host "UI: $name OK"
}
function Screenshot([string]$name) {
    $client=New-Object NativeTestWindow+Rect
    $point=New-Object NativeTestWindow+Point
    [NativeTestWindow]::GetClientRect($process.MainWindowHandle,[ref]$client) | Out-Null
    [NativeTestWindow]::ClientToScreen($process.MainWindowHandle,[ref]$point) | Out-Null
    $bitmap = New-Object System.Drawing.Bitmap(($client.Right-$client.Left),($client.Bottom-$client.Top))
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($point.X,$point.Y,0,0,$bitmap.Size)
        $bitmap.Save((Join-Path $build "native-$name.png"))
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
}
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:KIRBYCLICKER_DATA = $data
    $env:KIRBYCLICKER_SELFTEST_OUT = Join-Path $build 'native-selftest.json'
    $env:KIRBYCLICKER_STARTUP_OUT = Join-Path $data 'startup-ms.txt'
    $probe = Start-Process -FilePath $Exe -ArgumentList '--selftest' -WindowStyle Hidden -PassThru -Wait
    $report = Get-Content -LiteralPath $env:KIRBYCLICKER_SELFTEST_OUT -Raw | ConvertFrom-Json
    if ($probe.ExitCode -ne 0 -or -not $report.ok) { throw "Native self-test failed: $($report | ConvertTo-Json -Compress)" }
    Write-Host "SELFTEST: PASS ($($report.dry_run_clicks) dry-run clicks, $($report.gif_frames) GIF frames)"
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $Exe -PassThru
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "Native GUI exited: $($process.ExitCode)" }
        if ($process.MainWindowHandle -ne [IntPtr]::Zero -and (Test-Path -LiteralPath $env:KIRBYCLICKER_STARTUP_OUT)) { break }
        Start-Sleep -Milliseconds 20
    }
    if ($process.MainWindowHandle -eq [IntPtr]::Zero) { throw 'No native window appeared' }
    $startup = $clock.Elapsed.TotalMilliseconds
    $script:window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    Start-Sleep -Milliseconds 700
    Screenshot 'recorder'
    Click-Button 'Auto'
    Screenshot 'auto'
    Click-Button 'OFF'
    if (-not (Find-Button 'ON')) { throw 'Power did not turn ON' }
    Screenshot 'on'
    Click-Button 'ON'
    Click-Button '⚙'
    Screenshot 'settings'
    Click-Button 'Done'
    Click-Button 'Recorder'
    [NativeTestWindow]::SetWindowPos($process.MainWindowHandle,[IntPtr]::Zero,100,100,456,289,0x0004) | Out-Null
    Start-Sleep -Milliseconds 500
    Screenshot 'minimum'
    $bounds = $window.Current.BoundingRectangle
    foreach ($name in @('Load','Rename','Open folder','Compact')) {
        $button = Find-Button $name
        if ($button) {
            $r = $button.Current.BoundingRectangle
            if ($r.Width -gt 0 -and ($r.Left -lt $bounds.Left -or $r.Right -gt $bounds.Right)) { throw "Horizontal clipping: $name" }
        }
    }
    Click-Button 'Compact'
    $compactStyle = [NativeTestWindow]::GetWindowLongPtr($process.MainWindowHandle,-20).ToInt64()
    if (($compactStyle -band 0x08000000) -eq 0) { throw 'Compact window is missing WS_EX_NOACTIVATE' }
    Screenshot 'compact'
    Click-Button 'Restore'
    $before = $process.TotalProcessorTime.TotalMilliseconds
    Start-Sleep -Seconds 2
    $process.Refresh()
    $idleCpu = ($process.TotalProcessorTime.TotalMilliseconds - $before) / 2000 * 100
    $result = [ordered]@{ok=$true;exe_bytes=(Get-Item -LiteralPath $Exe).Length;external_startup_ms=[math]::Round($startup,1);internal_startup_ms=[double](Get-Content -LiteralPath $env:KIRBYCLICKER_STARTUP_OUT);idle_cpu_percent_one_core=[math]::Round($idleCpu,2);working_set_mb=[math]::Round($process.WorkingSet64/1MB,1);selftest=$report}
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $build 'native-gui-results.json')
    Write-Host ($result | ConvertTo-Json -Depth 6)
} finally {
    if ($process -and -not $process.HasExited) {
        [NativeTestWindow]::PostMessage($process.MainWindowHandle,0x0010,[IntPtr]::Zero,[IntPtr]::Zero) | Out-Null
        if (-not $process.WaitForExit(4000)) { $process.Kill() }
    }
    $env:PATH = $savedPath
    $env:KIRBYCLICKER_DATA = $savedData
    $env:KIRBYCLICKER_SELFTEST_OUT = $savedOutput
    $env:KIRBYCLICKER_STARTUP_OUT = $savedStartup
}
