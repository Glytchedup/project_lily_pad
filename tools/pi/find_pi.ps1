<#
Find the Lily Pad Raspberry Pi on the local network and confirm it over SSH. Read-only.

    pwsh tools/pi/find_pi.ps1            # prints the IP and a status line, exit 0 when found

Order: mDNS (lilypad.local) -> ARP cache for Raspberry Pi MAC prefixes -> ping-sweep the local DHCP subnet
then ARP again -> SSH-probe every live host with the Pi key. A host only counts once `ssh pi@<ip> hostname`
answers `lilypad` with ~/.ssh/lilypad_ed25519, so a stray router or NAS with port 22 open is never mistaken for it.
#>
param([string]$Key = "$HOME/.ssh/lilypad_ed25519", [string]$HostName = 'lilypad')
$ssh = 'C:\Program Files\Git\usr\bin\ssh.exe'
$sshOpts = @('-i', $Key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', '-o', 'StrictHostKeyChecking=no',
             '-o', 'UserKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR')

function Test-LilyPad([string]$ip) {
    $name = & $ssh @sshOpts "pi@$ip" 'hostname' 2>$null
    return ($LASTEXITCODE -eq 0 -and "$name".Trim() -eq $HostName)
}
function Report([string]$ip, [string]$how) {
    $info = & $ssh @sshOpts "pi@$ip" 'cat /proc/device-tree/model | tr -d "\0"; echo; findmnt -no FSTYPE /; cd ~/project_lily_pad 2>/dev/null && git log --oneline -1; systemctl is-active lilypad' 2>$null
    Write-Output "FOUND $ip (via $how)"
    $info | ForEach-Object { Write-Output "  $_" }
    exit 0
}

# 1. mDNS
try { $r = Resolve-DnsName "$HostName.local" -ErrorAction Stop | Where-Object IPAddress | Select-Object -First 1 } catch { $r = $null }
if ($r -and (Test-LilyPad $r.IPAddress)) { Report $r.IPAddress 'mDNS' }

# 2/3. ARP for Raspberry Pi OUIs, sweeping the subnet first if needed
$ouis = '^(2c-cf-67|d8-3a-dd|dc-a6-32|e4-5f-01|b8-27-eb|28-cd-c1|88-a2-9e)'
function Get-PiCandidates { Get-NetNeighbor -AddressFamily IPv4 | Where-Object { $_.LinkLayerAddress -and $_.LinkLayerAddress.ToLower() -match $ouis -and $_.State -ne 'Unreachable' } }
foreach ($n in Get-PiCandidates) { if (Test-LilyPad $n.IPAddress) { Report $n.IPAddress "ARP $($n.LinkLayerAddress)" } }

$nets = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq 'Dhcp' }
foreach ($net in $nets) {
    $bytes = ([Net.IPAddress]$net.IPAddress).GetAddressBytes(); [Array]::Reverse($bytes)
    $addr = [BitConverter]::ToUInt32($bytes, 0); $size = [math]::Pow(2, 32 - $net.PrefixLength)
    $base = $addr - ($addr % $size)
    $ips = for ($i = 1; $i -lt [math]::Min($size - 1, 1023); $i++) {
        $b = [BitConverter]::GetBytes([uint32]($base + $i)); [Array]::Reverse($b); ([Net.IPAddress]$b).ToString() }
    Write-Output "sweeping $($ips.Count) addresses on $($net.InterfaceAlias) ..."
    $ips | ForEach-Object -Parallel { Test-Connection $_ -Count 1 -TimeoutSeconds 1 -Quiet | Out-Null } -ThrottleLimit 128
}
foreach ($n in Get-PiCandidates) { if (Test-LilyPad $n.IPAddress) { Report $n.IPAddress "ARP $($n.LinkLayerAddress)" } }

# 4. any live host with SSH open
$live = Get-NetNeighbor -AddressFamily IPv4 | Where-Object { $_.State -in 'Reachable', 'Stale', 'Delay' }
foreach ($n in $live) {
    $c = New-Object Net.Sockets.TcpClient
    $open = $c.ConnectAsync($n.IPAddress, 22).Wait(700); $c.Close()
    if ($open -and (Test-LilyPad $n.IPAddress)) { Report $n.IPAddress 'SSH probe' }
}
Write-Output "NOT FOUND: the Pi is off, not on Ethernet, or on another network. It has no working Wi-Fi config (see docs/HANDOVER.md)."
exit 1
