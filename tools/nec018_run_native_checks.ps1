param(
 [Parameter(Mandatory=$true)][string]$CandidateRoot,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCandidateSha256,
 [Parameter(Mandatory=$true)][string]$EvidenceRoot,
 [ValidateSet('godot','unity','unreal')][string[]]$Engines=@('godot','unity','unreal'),
 [ValidateRange(1,3)][int]$Launches=3,
 [ValidateRange(30,600)][int]$TimeoutSeconds=150
)
$ErrorActionPreference='Stop'
function Assert-Plain([string]$Path){$i=Get-Item -LiteralPath $Path;if($i.Attributes -band [IO.FileAttributes]::ReparsePoint){throw ('Link/reparse point refused: '+$Path)}}
function Child([string]$Root,[string]$Relative){
 if([IO.Path]::IsPathRooted($Relative) -or $Relative -match '[\\:]' -or @($Relative.Split('/') | Where-Object {$_ -in @('','.','..') -or $_ -match '[. ]$|[<>"|?*]' -or $_.Split('.')[0] -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$'}).Count){throw 'Unsafe relative path'}
 $full=[IO.Path]::GetFullPath((Join-Path $Root $Relative));$base=[IO.Path]::GetFullPath($Root).TrimEnd('\');if(-not $full.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Escaped payload root'}
 $cursor=$full;while($cursor.Length -ge $base.Length){if(Test-Path -LiteralPath $cursor){Assert-Plain $cursor};$next=Split-Path -Parent $cursor;if($next -eq $cursor -or -not $next){break};$cursor=$next};return $full
}
function Inventory([string]$Root){$map=@{};foreach($f in Get-ChildItem -LiteralPath $Root -Recurse -Force){Assert-Plain $f.FullName;if(-not $f.PSIsContainer){$key=$f.FullName.Substring($Root.TrimEnd('\').Length+1).Replace('\','/');if($map.ContainsKey($key)){throw 'Aliased file path'};$map[$key]=@{bytes=$f.Length;sha256=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}}};return $map}
function Verify-Inventory([string]$Root,$Expected){$actual=Inventory $Root;$names=@($Expected.PSObject.Properties.Name);if($actual.Count -ne $names.Count){throw 'Payload file set changed'};foreach($name in $names){$null=Child $Root $name;$row=$Expected.$name;if(-not $actual.ContainsKey($name) -or $actual[$name].sha256 -ne $row.sha256 -or $actual[$name].bytes -ne $row.bytes){throw ('Payload hash/size changed: '+$name)}}}
function Need-True($Object,[string[]]$Names){foreach($name in $Names){$p=$Object.PSObject.Properties[$name];if(-not $p -or $p.Value -isnot [bool] -or -not $p.Value){throw ('Native assertion failed: '+$name)}}}
$CandidateRoot=(Resolve-Path -LiteralPath $CandidateRoot).Path;Assert-Plain $CandidateRoot
$manifest=Join-Path $CandidateRoot 'candidate.json';Assert-Plain $manifest
if((Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedCandidateSha256){throw 'Candidate differs from independently supplied digest'}
$candidate=Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
$signed=($candidate.schema -eq 'xace.nec018.handoff.v2' -and $candidate.classification -eq 'signed_private_engineering_not_release_certified')
if(-not $signed -and ($candidate.schema -ne 'xace.nec018.handoff.v1' -or $candidate.classification -ne 'unsigned_private_engineering_not_release_certified')){throw 'Unsupported candidate classification'}
if($signed -and ($candidate.publisher_policy.schema -ne 'xace.publisher_policy.v1' -or $candidate.publisher_policy.trust_policy -ne 'windows_authenticode_cached_chain.v1' -or -not $candidate.publisher_policy.allowed_signer_certificate_sha256)){throw 'Explicit approved publisher policy required'}
foreach($name in @($candidate.tools.PSObject.Properties.Name)){if((Get-FileHash -LiteralPath (Child $CandidateRoot $name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $candidate.tools.$name){throw 'Handoff tool changed'}}
$EvidenceRoot=[IO.Path]::GetFullPath($EvidenceRoot)
if((Test-Path -LiteralPath $EvidenceRoot) -or $EvidenceRoot.StartsWith($CandidateRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or $CandidateRoot.StartsWith($EvidenceRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or $EvidenceRoot.Split('\') -match '^(target|build|dist|tmp|temp|\.cache)$'){throw 'Fresh persistent output outside candidate required'}
$null=New-Item -ItemType Directory -Path $EvidenceRoot
& (Join-Path $CandidateRoot 'Collect-Environment.ps1') -OutputPath (Join-Path $EvidenceRoot 'environment.json')
$environment=Get-Content -LiteralPath (Join-Path $EvidenceRoot 'environment.json') -Raw | ConvertFrom-Json
$oldPath=$env:PATH;$oldLocal=$env:LOCALAPPDATA;$runs=New-Object 'System.Collections.Generic.List[object]';$signatures=New-Object 'System.Collections.Generic.List[object]';$technical=$false;$failure=$null
try{
 foreach($engine in $Engines){
  $profile=$candidate.profiles.$engine;if($profile.root -ne ('payload/'+$engine)){throw 'Unexpected engine root'};$root=Child $CandidateRoot $profile.root;Verify-Inventory $root $profile.files
  foreach($name in @($profile.files.PSObject.Properties.Name | Where-Object {$_ -match '\.exe$'})){$sig=Get-AuthenticodeSignature -LiteralPath (Child $root $name);$signatures.Add(@{engine=$engine;path=$name;status=$sig.Status.ToString();signer_thumbprint=if($sig.SignerCertificate){$sig.SignerCertificate.Thumbprint}else{$null}})}
  if($signed){
   $required=@($profile.required_signed_executables)+@(($profile.common_release_root+'/xace-player-launcher.exe'),($profile.common_release_root+'/package/runtime/xace_runtime.exe'))
   foreach($relative in $required){
    $signature=Get-AuthenticodeSignature -LiteralPath (Child $root $relative)
    if($signature.Status -ne 'Valid' -or $signature.SignatureType.ToString() -ne 'Authenticode' -or -not $signature.SignerCertificate -or -not $signature.TimeStamperCertificate){throw ('Valid timestamped embedded signature required: '+$relative)}
    $algorithm=[Security.Cryptography.SHA256]::Create();try{$certificate=([BitConverter]::ToString($algorithm.ComputeHash($signature.SignerCertificate.RawData))).Replace('-','').ToLowerInvariant()}finally{$algorithm.Dispose()}
    if($certificate -notin $candidate.publisher_policy.allowed_signer_certificate_sha256){throw ('Publisher differs from independently approved candidate: '+$relative)}
   }
  }
  for($n=0;$n -lt $Launches;$n++){
   $case=Join-Path $EvidenceRoot ($engine+'-'+$n);$null=New-Item -ItemType Directory -Path $case;$report=Join-Path $case 'player.json';$log=Join-Path $case 'engine.log'
   $env:PATH=Join-Path $env:SystemRoot 'System32';$env:LOCALAPPDATA=Join-Path $EvidenceRoot 'isolated-user-data';$null=New-Item -ItemType Directory -Path $env:LOCALAPPDATA -Force
   $argv=@();foreach($arg in $profile.argv){if($arg -isnot [string] -or $arg -match '["\r\n]' -or $arg.Replace('{report}','').Replace('{log}','') -match '[{}]'){throw 'Unsafe argument template'};$argv+=('"'+$arg.Replace('{report}',$report).Replace('{log}',$log)+'"')}
   $started=[DateTime]::UtcNow;$process=$null;$stdoutTask=$null;$stderrTask=$null;$observations=New-Object 'System.Collections.Generic.List[object]';$networkComplete=$true
   try{
    # Retain the process handle ourselves: Windows PowerShell Start-Process can
    # lose ExitCode for a short-lived process when polled with Refresh().
    $process=New-Object Diagnostics.Process
    $process.StartInfo.FileName=Child $root $profile.entry
    $process.StartInfo.Arguments=$argv -join ' '
    $process.StartInfo.WorkingDirectory=$root
    $process.StartInfo.UseShellExecute=$false
    $process.StartInfo.CreateNoWindow=$true
    $process.StartInfo.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden
    $process.StartInfo.RedirectStandardOutput=$true
    $process.StartInfo.RedirectStandardError=$true
    if(-not $process.Start()){throw 'Native process did not start'}
    $stdoutTask=$process.StandardOutput.ReadToEndAsync();$stderrTask=$process.StandardError.ReadToEndAsync()
    while(-not $process.HasExited){
     if(([DateTime]::UtcNow-$started).TotalSeconds -gt $TimeoutSeconds){throw 'Owned native test timed out'}
     try{$all=@(Get-CimInstance Win32_Process -ErrorAction Stop);$ids=@($process.Id);do{$added=@($all | Where-Object {$_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids} | Select-Object -ExpandProperty ProcessId);$ids+=$added}while($added.Count -gt 0);$connections=@(Get-NetTCPConnection -ErrorAction Stop | Where-Object {$_.OwningProcess -in $ids} | Select-Object OwningProcess,LocalAddress,LocalPort,RemoteAddress,RemotePort,State);$observations.Add(@{utc=[DateTime]::UtcNow.ToString('o');processes=@($all | Where-Object {$_.ProcessId -in $ids} | Select-Object ProcessId,ParentProcessId,Name);tcp=$connections})}catch{$networkComplete=$false}
     Start-Sleep -Milliseconds 250;$process.Refresh()
    }
    $process.WaitForExit();$exit=$process.ExitCode
   }finally{
    if($process -and -not $process.HasExited){$process.Refresh();if(-not $process.HasExited){& taskkill.exe /PID $process.Id /T /F | Out-Null}}
    foreach($capture in @(@{task=$stdoutTask;name='stdout.log'},@{task=$stderrTask;name='stderr.log'})){
     if($capture.task -and $capture.task.Wait(5000)){[IO.File]::WriteAllText((Join-Path $case $capture.name),$capture.task.Result,(New-Object Text.UTF8Encoding($false)))}
    }
   }
   [IO.File]::WriteAllText((Join-Path $case 'process-network.json'),(ConvertTo-Json -InputObject $observations.ToArray() -Depth 12),(New-Object Text.UTF8Encoding($false)))
   if(-not(Test-Path -LiteralPath $report)){throw 'Structured native report missing'};$value=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json;Need-True $value @('ok')
   if($engine -eq 'godot'){Need-True $value @('exported');if($value.objects -ne $profile.objects -or $value.tick -lt 30){throw 'Godot object/tick mismatch'}}
   if($engine -eq 'unity'){Need-True $value @('native_identity','hierarchy','positions','input_moves_authority','save_compatible_not_restored','incompatible_save_retained');if($value.entities -ne $profile.objects -or $value.tick -lt 12){throw 'Unity object/tick mismatch'}}
   if($engine -eq 'unreal'){Need-True $value @('packaged','native_identity','exact_projection','mesh_material_retained','static_objects_unchanged','authoritative_input','process_cleanup');if($value.objects -ne $profile.objects -or $value.tick -lt 30){throw 'Unreal object/tick mismatch'}}
   foreach($id in @($value.runtime_pid,$value.owner_pid)){if($null -eq $id -or [long]$id -le 0){throw 'Owned runtime/launcher identity missing'};if(Get-Process -Id $id -ErrorAction SilentlyContinue){throw 'Reported owned process survived game shutdown'}}
   if($null -eq $exit -or $exit -ne 0){throw ('Native game exited '+$exit)};Verify-Inventory $root $profile.files
   $runs.Add(@{engine=$engine;iteration=$n;technical_pass=$true;exit_code=$exit;native_report_sha256=(Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant();owned_process_cleanup=$true;installation_unchanged=$true;process_tcp_sampling_complete=$networkComplete;packet_capture_performed=$false;elapsed_seconds=([DateTime]::UtcNow-$started).TotalSeconds})
   Write-Output ($engine+' native launch '+$n+' passed')
  }
 }
 $technical=$true
}catch{$failure=$_.Exception.Message;Write-Warning $failure}finally{
 $env:PATH=$oldPath;$env:LOCALAPPDATA=$oldLocal
 $result=[ordered]@{schema='xace.nec018.native_run.v1';candidate_digest=$ExpectedCandidateSha256;machine_id=$environment.machine_id;same_development_machine=($environment.machine_id -eq $candidate.development_machine_id);technical_checks_passed=$technical;failure=$failure;runs=$runs.ToArray();signatures=$signatures.ToArray();launches_per_engine=$Launches;environment_eligible_for_clean_review=($environment.os_64_bit -eq $true -and $environment.os -and $environment.machine_id -and $environment.machine_id -ne $candidate.development_machine_id -and @($environment.development_indicators).Count -eq 0 -and @($environment.collection_errors).Count -eq 0);offline_interfaces_observed=$environment.offline_interfaces_observed;clean_machine_certified=$false;release_certified=$false;steam_certified=$false;human_walkthrough_performed=$false;update_uninstall_matrix_performed=$false;notes='Structured fixture probes use automated declared input. This is not physical-device, fresh-OS, packet-capture, human-workflow, signing or update/uninstall certification.'}
 [IO.File]::WriteAllText((Join-Path $EvidenceRoot 'result.json'),($result | ConvertTo-Json -Depth 18),(New-Object Text.UTF8Encoding($false)))
}
if(-not $technical){exit 1}
