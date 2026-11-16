param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $OutputPath){throw 'Create-only environment output required'}
$errors=New-Object 'System.Collections.Generic.List[string]'
function Hash-Text([string]$Text){$h=[Security.Cryptography.SHA256]::Create();try{([BitConverter]::ToString($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}}
$machine=$null
try{$guid=(Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid;if(-not $guid){throw 'MachineGuid absent'};$machine=Hash-Text $guid}catch{$errors.Add('Machine identity unavailable')}
$os=$null;$cpu=@();$gpu=@()
try{$os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory}catch{$errors.Add('OS CIM query unavailable')}
try{$cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)}catch{$errors.Add('CPU CIM query unavailable')}
try{$gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion)}catch{$errors.Add('GPU CIM query unavailable')}
$indicators=New-Object 'System.Collections.Generic.List[string]'
foreach($tool in @('cargo','rustc','python','python3','node','npm','Unity','UnrealEditor','Godot','XACEBuilder')){if(Get-Command $tool -ErrorAction SilentlyContinue){$indicators.Add('command:'+ $tool)}}
foreach($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')){
 if(Test-Path -LiteralPath $key){try{foreach($entry in Get-ChildItem -LiteralPath $key){$name=(Get-ItemProperty -LiteralPath $entry.PSPath -ErrorAction Stop).DisplayName;if($name -and $name -match 'Unity|Unreal|Godot|Python|Node.js|Rust Toolchain|Visual Studio|XACE Builder'){$indicators.Add('installed:'+ $name)}}}catch{$errors.Add('Installed-software query incomplete')}}
}
foreach($known in @("$env:ProgramFiles\Unity","$env:ProgramFiles\Epic Games\UE_5.7","$env:USERPROFILE\.cargo\bin\rustc.exe","$env:USERPROFILE\XACE-Recovery","$env:USERPROFILE\Downloads\xace")){if(Test-Path -LiteralPath $known){$indicators.Add('known_development_location:'+ (Split-Path -Leaf $known))}}
$adapters=@();$networkKnown=$false
try{$adapters=@(Get-NetAdapter -IncludeHidden -ErrorAction Stop | Select-Object Name,InterfaceDescription,Status);$networkKnown=$true}catch{$errors.Add('Network adapter query unavailable')}
$up=@($adapters | Where-Object {$_.Status -eq 'Up' -and $_.InterfaceDescription -notmatch 'Loopback'})
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$result=[ordered]@{schema='xace.nec018.environment.v1';recorded_utc=[DateTime]::UtcNow.ToString('o');machine_id=$machine;os=$os;cpu=$cpu;gpu=$gpu;admin_token=$admin;os_64_bit=[Environment]::Is64BitOperatingSystem;powershell=$PSVersionTable.PSVersion.ToString();development_indicators=@($indicators | Sort-Object -Unique);collection_errors=@($errors);network_adapters=$adapters;remote_capable_adapters_up=$up.Count;offline_interfaces_observed=($networkKnown -and $up.Count -eq 0);packet_capture_performed=$false;fresh_install_proven=$false;clean_machine_certified=$false}
$parent=Split-Path -Parent ([IO.Path]::GetFullPath($OutputPath));if(-not(Test-Path -LiteralPath $parent)){throw 'Existing persistent evidence parent required'}
[IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath),($result | ConvertTo-Json -Depth 12),(New-Object Text.UTF8Encoding($false)))
