[CmdletBinding()]
param(
    [string]$PythonwPath = "D:\ComfyUI_Mie\python_embeded\pythonw.exe",
    [string]$PythonPath = "D:\ComfyUI_Mie\python_embeded\python.exe",
    [string]$WatchdogScript = "",
    [int]$StartupTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($WatchdogScript)) {
    $WatchdogScript = Join-Path (Split-Path $PSScriptRoot -Parent) "comfy_watchdog.py"
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ComfyPanelCommandLine
{
    [DllImport("shell32.dll", SetLastError = true)]
    private static extern IntPtr CommandLineToArgvW(
        [MarshalAs(UnmanagedType.LPWStr)] string commandLine,
        out int argumentCount);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    public static string[] Split(string commandLine)
    {
        int count;
        IntPtr values = CommandLineToArgvW(commandLine, out count);
        if (values == IntPtr.Zero) {
            throw new System.ComponentModel.Win32Exception();
        }
        try {
            string[] result = new string[count];
            for (int index = 0; index < count; index++) {
                IntPtr value = Marshal.ReadIntPtr(values, index * IntPtr.Size);
                result[index] = Marshal.PtrToStringUni(value);
            }
            return result;
        }
        finally {
            LocalFree(values);
        }
    }
}
'@

function Resolve-RequiredFile([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
}

function Test-ExactCommandLine(
    [object]$Process,
    [string]$ExpectedExecutable,
    [string[]]$ExpectedArguments,
    [int[]]$PathArgumentIndexes
) {
    if ([string]::IsNullOrWhiteSpace([string]$Process.ExecutablePath) -or
        [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) {
        return $false
    }
    try {
        $actualExecutable = [System.IO.Path]::GetFullPath([string]$Process.ExecutablePath)
        $tokens = [ComfyPanelCommandLine]::Split([string]$Process.CommandLine)
    }
    catch {
        return $false
    }
    if (-not [string]::Equals(
            $actualExecutable, $ExpectedExecutable,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    if ($tokens.Length -ne ($ExpectedArguments.Length + 1)) {
        return $false
    }
    $expected = @($ExpectedExecutable) + $ExpectedArguments
    for ($index = 0; $index -lt $expected.Length; $index++) {
        $comparison = [System.StringComparison]::Ordinal
        if ($PathArgumentIndexes -contains $index) {
            $comparison = [System.StringComparison]::OrdinalIgnoreCase
            try {
                $tokens[$index] = [System.IO.Path]::GetFullPath($tokens[$index])
                $expected[$index] = [System.IO.Path]::GetFullPath($expected[$index])
            }
            catch {
                return $false
            }
        }
        if (-not [string]::Equals($tokens[$index], $expected[$index], $comparison)) {
            return $false
        }
    }
    return $true
}

function Get-WatchdogStatusHash {
    try {
        $status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8198/status" -TimeoutSec 2
        $hash = [string]$status.dreamapi_contract_sha256
        if ($hash -match '^[0-9a-f]{64}$') {
            return $hash
        }
    }
    catch {
        return $null
    }
    return $null
}

function Get-ExactWatchdogs([string]$Executable, [string]$Script) {
    return @(Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object {
        Test-ExactCommandLine $_ $Executable @($Script) @(0, 1)
    })
}

function Get-ExactDreamApiWorkers([string]$Executable, [string]$Script) {
    return @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        Test-ExactCommandLine $_ $Executable @($Script, "--dreamapi-worker") @(0, 1)
    })
}

function Get-ProjectTunnelArguments([string]$SshKey) {
    return @(
        "-i", $SshKey, "-p", "22", "-N",
        "-R", "8199:127.0.0.1:8188",
        "-R", "8198:127.0.0.1:8198",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "admin@8.210.125.65"
    )
}

function Get-ProjectTunnels([string]$SshExecutable, [string]$SshKey) {
    $arguments = @(Get-ProjectTunnelArguments $SshKey)
    return @(Get-CimInstance Win32_Process -Filter "Name = 'ssh.exe'" | Where-Object {
        Test-ExactCommandLine $_ $SshExecutable $arguments @(0, 2)
    })
}

function Stop-ExactProcesses(
    [object[]]$Processes,
    [string]$Label,
    [string]$ExpectedExecutable,
    [string[]]$ExpectedArguments,
    [int[]]$PathArgumentIndexes
) {
    foreach ($item in $Processes) {
        $processIdProperty = $item.PSObject.Properties["ProcessId"]
        $idProperty = $item.PSObject.Properties["Id"]
        if ($null -ne $processIdProperty) {
            $candidateProcessId = [int]$processIdProperty.Value
        }
        elseif ($null -ne $idProperty) {
            $candidateProcessId = [int]$idProperty.Value
        }
        else {
            throw "$Label process object does not expose a PID"
        }
        $current = @(Get-CimInstance Win32_Process `
            -Filter "ProcessId = $candidateProcessId" -ErrorAction Stop)
        if ($current.Count -eq 0) {
            Write-Output "$Label already exited: PID $candidateProcessId"
            continue
        }
        if ($current.Count -ne 1) {
            throw "$Label PID lookup was ambiguous: PID $candidateProcessId"
        }
        if (-not (Test-ExactCommandLine $current[0] $ExpectedExecutable `
                $ExpectedArguments $PathArgumentIndexes)) {
            Write-Output "$Label not stopped because its identity changed: PID $candidateProcessId"
            continue
        }
        Stop-Process -Id $candidateProcessId -Force -ErrorAction Stop
        Write-Output "$Label stopped: PID $candidateProcessId"
    }
}

$PythonwPath = Resolve-RequiredFile $PythonwPath "Embedded pythonw"
$PythonPath = Resolve-RequiredFile $PythonPath "Embedded python"
$WatchdogScript = Resolve-RequiredFile $WatchdogScript "Watchdog script"
$sshExecutable = Resolve-RequiredFile "C:\Windows\System32\OpenSSH\ssh.exe" "OpenSSH client"
$sshKey = Resolve-RequiredFile (Join-Path (Split-Path $PSScriptRoot -Parent) "tools\id_ed25519") "SSH key"

$hashOutput = @(& $PythonPath $WatchdogScript --contract-sha256)
if ($LASTEXITCODE -ne 0 -or $hashOutput.Count -ne 1 -or
    [string]$hashOutput[0] -notmatch '^[0-9a-f]{64}$') {
    throw "Unable to compute the watchdog DreamAPI contract hash"
}
$expectedHash = [string]$hashOutput[0]
$watchdogArguments = @($WatchdogScript)
$watchdogPathArgumentIndexes = @(0, 1)
$projectTunnelArguments = @(Get-ProjectTunnelArguments $sshKey)
$projectTunnelPathArgumentIndexes = @(0, 2)
$dreamApiWorkers = @(Get-ExactDreamApiWorkers $PythonPath $WatchdogScript)
if ($dreamApiWorkers.Count -gt 0) {
    throw "DreamAPI paid worker is active; no process was stopped"
}
$watchdogs = @(Get-ExactWatchdogs $PythonwPath $WatchdogScript)
$watchdogProcessIds = @($watchdogs | ForEach-Object { [int]$_.ProcessId })
$observedHash = Get-WatchdogStatusHash

if ($watchdogs.Count -gt 0 -and $observedHash -eq $expectedHash) {
    $orphanTunnels = @(Get-ProjectTunnels $sshExecutable $sshKey | Where-Object {
        $watchdogProcessIds -notcontains [int]$_.ParentProcessId
    })
    Stop-ExactProcesses $orphanTunnels "Orphan project tunnel" `
        $sshExecutable $projectTunnelArguments $projectTunnelPathArgumentIndexes
    Write-Output "Watchdog reused: contract $expectedHash"
    exit 0
}

if ($watchdogs.Count -eq 0 -and $null -ne $observedHash) {
    throw "Port 8198 is served by an unmanaged process; no process was stopped"
}

Stop-ExactProcesses $watchdogs "Outdated watchdog" `
    $PythonwPath $watchdogArguments $watchdogPathArgumentIndexes
if ($watchdogs.Count -gt 0) {
    Start-Sleep -Milliseconds 500
}
Stop-ExactProcesses @(Get-ProjectTunnels $sshExecutable $sshKey) `
    "Orphan project tunnel" $sshExecutable $projectTunnelArguments `
    $projectTunnelPathArgumentIndexes

$started = Start-Process -FilePath $PythonwPath -ArgumentList @($WatchdogScript) `
    -WindowStyle Hidden -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
do {
    if ($started.HasExited) {
        throw "Watchdog exited during startup with code $($started.ExitCode)"
    }
    $observedHash = Get-WatchdogStatusHash
    if ($observedHash -eq $expectedHash) {
        Write-Output "Watchdog started: PID $($started.Id), contract $expectedHash"
        exit 0
    }
    Start-Sleep -Milliseconds 250
} while ([DateTime]::UtcNow -lt $deadline)

if (-not $started.HasExited) {
    Stop-ExactProcesses @($started) "Failed watchdog startup" `
        $PythonwPath $watchdogArguments $watchdogPathArgumentIndexes
}
throw "Watchdog startup did not expose the expected DreamAPI contract hash"
