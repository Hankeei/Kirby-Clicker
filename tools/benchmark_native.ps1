param(
    [string]$Native = (Join-Path $PSScriptRoot '..\dist\KirbyClicker.exe'),
    [string]$Python = (Join-Path $PSScriptRoot '..\build\KirbyClicker-v1.2.exe')
)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$originalData=$env:KIRBYCLICKER_DATA
$originalPath=$env:PATH
$samples=@()
try {
    $env:PATH="$env:SystemRoot\System32;$env:SystemRoot"
    foreach($trial in 1..3) {
        foreach($entry in @(@('Rust',$Native),@('Python v1.2',$Python))) {
            $label=$entry[0];$exe=(Resolve-Path -LiteralPath $entry[1]).Path
            $data=Join-Path $root ('build\bench-'+[guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $data | Out-Null
            '{"music_enabled":false}' | Set-Content -LiteralPath (Join-Path $data 'settings.json')
            $env:KIRBYCLICKER_DATA=$data
            $clock=[Diagnostics.Stopwatch]::StartNew()
            $launcher=Start-Process -FilePath $exe -PassThru
            $name=[IO.Path]::GetFileNameWithoutExtension($exe)
            $windowProcess=$null
            try {
                $deadline=(Get-Date).AddSeconds(30)
                while((Get-Date)-lt $deadline) {
                    $candidates=Get-Process -Name $name -ErrorAction SilentlyContinue
                    foreach($candidate in $candidates) {
                        if($candidate.MainWindowHandle -ne [IntPtr]::Zero -and $candidate.MainWindowTitle -eq 'Kirby Clicker') {
                            $w=[System.Windows.Automation.AutomationElement]::FromHandle($candidate.MainWindowHandle)
                            if($w.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition).Count -ge 8) {$windowProcess=$candidate;break}
                        }
                    }
                    if($windowProcess){break}
                    Start-Sleep -Milliseconds 15
                }
                if(-not $windowProcess){throw "No ready window for $label"}
                $ready=$clock.Elapsed.TotalMilliseconds
                Start-Sleep -Milliseconds 500
                $windowProcess.Refresh();$cpu=$windowProcess.TotalProcessorTime.TotalMilliseconds
                Start-Sleep -Seconds 1
                $windowProcess.Refresh()
                $s=[pscustomobject]@{implementation=$label;trial=$trial;ready_ms=[math]::Round($ready,1);idle_cpu_percent_one_core=[math]::Round(($windowProcess.TotalProcessorTime.TotalMilliseconds-$cpu)/10,2);working_set_mb=[math]::Round($windowProcess.WorkingSet64/1MB,1);exe_bytes=(Get-Item -LiteralPath $exe).Length}
                $samples+=$s;Write-Host ($s|ConvertTo-Json -Compress)
            } finally {
                if($windowProcess -and -not $windowProcess.HasExited){$windowProcess.CloseMainWindow()|Out-Null;if(-not $windowProcess.WaitForExit(4000)){$windowProcess.Kill()}}
                if(-not $launcher.WaitForExit(4000)){$launcher.Kill()}
            }
        }
    }
    $samples | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'build\native-benchmark.json')
} finally {$env:PATH=$originalPath;$env:KIRBYCLICKER_DATA=$originalData}
