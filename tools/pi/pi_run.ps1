<#
Run a shell script on the Lily Pad Pi, or copy a file off it, from Windows.

    pwsh tools/pi/pi_run.ps1 -Script check.sh             # run a local script on the Pi as user pi
    pwsh tools/pi/pi_run.ps1 -Command 'free -m; uptime'   # run an inline command string
    pwsh tools/pi/pi_run.ps1 -Script test.sh -Restart     # always start lilypad afterwards, even on failure
    pwsh tools/pi/pi_run.ps1 -Fetch /run/lilypad/frame.png -To C:/tmp/frame.png

Why this exists: piping a multi-line string from PowerShell into `ssh ... bash -s` gives every line a
trailing CR. `systemctl start lilypad` then fails with `Invalid unit name "lilypad\r"` and leaves the
kiosk stopped. This script normalises the script to LF, copies it over with scp, runs it, and with -Restart
always finishes with `sudo systemctl start lilypad` and checks that the service is active.
-Fetch copies bytes with scp. Do not use Set-Content for this: it drops the file's line breaks.

The script runs as `pi`, which has passwordless sudo. Target: pi@lilypad.local (override with -HostName).
Exit code: the remote script's exit code, or 1 when -Restart could not bring the service back.
#>
param(
    [string]$Script,
    [string]$Command,
    [switch]$Restart,
    [string]$Fetch,
    [string]$To,
    [string]$HostName = 'lilypad.local',
    [string]$Key = "$HOME/.ssh/lilypad_ed25519"
)
$ErrorActionPreference = 'Stop'
$git = 'C:\Program Files\Git\usr\bin'
$opts = @('-i', $Key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'LogLevel=ERROR')
$target = "pi@$HostName"

if ($Fetch) {
    if (-not $To) { $To = Join-Path (Get-Location) (Split-Path $Fetch -Leaf) }
    & "$git\scp.exe" @opts "${target}:$Fetch" $To
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Output "fetched $Fetch -> $To ($((Get-Item $To).Length) bytes)"
    exit 0
}

if ($Script) { $body = [IO.File]::ReadAllText((Resolve-Path $Script)) }
elseif ($Command) { $body = $Command }
else { throw 'Give -Script <file>, -Command <string> or -Fetch <remote path>.' }

$body = $body -replace "`r", ''
$local = [IO.Path]::GetTempFileName()
$remote = "/tmp/pi_run_$([guid]::NewGuid().ToString('N').Substring(0, 8)).sh"
try {
    [IO.File]::WriteAllText($local, $body + "`n", [Text.UTF8Encoding]::new($false))
    & "$git\scp.exe" @opts $local "${target}:$remote"
    if ($LASTEXITCODE -ne 0) { throw "scp to $target failed" }
    & "$git\ssh.exe" @opts $target "bash $remote; rc=`$?; rm -f $remote; exit `$rc"
    $rc = $LASTEXITCODE
} finally {
    Remove-Item $local -ErrorAction SilentlyContinue
    if ($Restart) {
        $state = & "$git\ssh.exe" @opts $target 'sudo systemctl start lilypad; sleep 2; systemctl is-active lilypad'
        Write-Output "lilypad: $state"
        if ("$state".Trim() -ne 'active') { $rc = 1 }
    }
}
exit $rc
