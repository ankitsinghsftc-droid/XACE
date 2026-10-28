param([Parameter(Mandatory=$true)][string]$ProofRoot,[string]$RunName="firewall-run")
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($ProofRoot)
$allowed='C:\Users\ankit\XACE-Recovery\worktrees\xace\evidence\nec016\'
if(-not $root.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected proof root'}
if($RunName -notmatch '^firewall-run(-[a-z0-9]+)?$'){throw 'Invalid run name'}
$run=Join-Path $root $RunName
if(Test-Path -LiteralPath $run){throw 'Fresh proof directory required'}
New-Item -ItemType Directory -Path $run | Out-Null
$game=Join-Path $root 'build\shipping\NativeGame.exe'
$launcher=Join-Path $root 'build\shipping\release\xace-player-launcher.exe'
$runtime=Join-Path $root 'build\shipping\release\package\runtime\xace_runtime.exe'
$programs=@($game,$launcher,$runtime)
$rules=@();$result=@{ok=$false;network_denied=$false;clean_machine=$false;rules_removed=$false}
function Run-Native([string]$output,[string]$data,[bool]$probe){
 $env:LOCALAPPDATA=Join-Path $run $data
 $env:PATH=Join-Path $env:SystemRoot 'System32'
 $nativeArgs=@('--headless','--',(Join-Path $run $output))
 if($probe){$nativeArgs+='--network-probe'}
 $info=[Diagnostics.ProcessStartInfo]::new()
 $info.FileName=$game
 $info.Arguments=($nativeArgs | ForEach-Object {'"'+$_+'"'}) -join ' '
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $process=[Diagnostics.Process]::Start($info)
 $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
 if(-not $process.WaitForExit(60000)){throw 'Native proof timeout; process preserved for diagnosis'}
 [IO.File]::WriteAllText((Join-Path $run ($output+'.stdout.txt')),$stdout.Result)
 [IO.File]::WriteAllText((Join-Path $run ($output+'.stderr.txt')),$stderr.Result)
 $exitCode=$process.ExitCode
 @{exit_code=$exitCode;arguments=$nativeArgs;pid=$process.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run ($output+'.process.json'))
 $process.Dispose()
 if($exitCode -ne 0){throw "Native proof exited with code $exitCode"}
 return (Get-Content -Raw -LiteralPath (Join-Path $run $output) | ConvertFrom-Json)
}
try {
 $baseline=Get-Content -Raw -LiteralPath (Join-Path $root 'baseline.json') | ConvertFrom-Json
 if(-not $baseline.connected){throw 'Positive connectivity baseline required'}
 $pins=@{};foreach($program in $programs){$pins[$program]=(Get-FileHash -LiteralPath $program -Algorithm SHA256).Hash}
 $pins | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'executables.json')
 foreach($program in $programs){
  $name='XACE-NEC016-'+[Guid]::NewGuid().ToString('N')
  $rules+=$name
  New-NetFirewallRule -Name $name -DisplayName $name -Direction Outbound -Program $program -Action Block -Profile Any -Enabled True -RemoteAddress @('0.0.0.0-126.255.255.255','128.0.0.0-255.255.255.255','::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff') | Out-Null
 }
 $rules | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'created-rule-names.json')
 $records=foreach($name in $rules){$rule=Get-NetFirewallRule -Name $name;[PSCustomObject]@{name=$name;enabled=[string]$rule.Enabled;action=[string]$rule.Action;direction=[string]$rule.Direction;program=($rule | Get-NetFirewallApplicationFilter).Program;remote=($rule | Get-NetFirewallAddressFilter).RemoteAddress}}
 $records | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $run 'active-rules.json')
 $denied=Run-Native 'denied.json' 'denied-data' $true
 if($denied.connected){throw 'Native executable still has external connectivity'}
 $control=[Net.Sockets.TcpClient]::new();try{$task=$control.ConnectAsync('1.1.1.1',443);if(-not $task.Wait(8000) -or -not $control.Connected){throw 'Unblocked endpoint control failed'}}finally{$control.Dispose()}
 $player=Run-Native 'player.json' 'player-data' $false
 if(-not $player.ok){throw 'Gameplay failed under network denial'}
 $result.network_denied=$true;$result.gameplay=$player;$result.unblocked_control_connected=$true;$result.loopback_preserved=$true;$result.ok=$true
} catch {$result.error=$_.Exception.Message}
finally {
 foreach($name in $rules){try{Remove-NetFirewallRule -Name $name -ErrorAction Stop}catch{$result.ok=$false;$result.cleanup_error=$_.Exception.Message}}
 $remaining=@(foreach($name in $rules){Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue})
 $result.rules_removed=($remaining.Count -eq 0)
 if(-not $result.rules_removed){$result.ok=$false}
 $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $run 'result.json')
}
if(-not $result.ok){exit 1}
