param(
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$ExpectedPlanSha,
    [Parameter(Mandatory=$true)][string]$ReceiptDirectory,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $Workspace).Path.TrimEnd('\')
$planFile = (Resolve-Path -LiteralPath $Plan).Path
if ((Get-FileHash -LiteralPath $planFile -Algorithm SHA256).Hash -ine $ExpectedPlanSha) { throw 'Plan hash mismatch' }
$proposal = Get-Content -LiteralPath $planFile -Raw -Encoding utf8 | ConvertFrom-Json
if ([IO.Path]::GetFullPath($proposal.workspace).TrimEnd('\') -ine $root) { throw 'Wrong workspace' }
function Resolve-SafeChild([string]$Path) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    if (-not $resolved.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Outside workspace: $resolved" }
    $cursor = $resolved
    while ($cursor -ine $root) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse ancestor: $cursor" }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $resolved
}
$receiptRoot = [IO.Path]::GetFullPath($ReceiptDirectory)
if (-not $receiptRoot.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Receipt outside workspace' }
Resolve-SafeChild ([IO.Path]::GetDirectoryName($receiptRoot)) | Out-Null
New-Item -ItemType Directory -Path $receiptRoot -Force | Out-Null
$receiptRoot = Resolve-SafeChild $receiptRoot
$preflight = Join-Path $receiptRoot 'preflight.json'
$receiptFile = Join-Path $receiptRoot 'removed.json'
if ((Test-Path -LiteralPath $preflight) -or (Test-Path -LiteralPath $receiptFile)) { throw 'Use a new receipt directory' }

# Python only reads and hashes. All mutations below are native PowerShell.
& (Join-Path $root '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'verify_plan.py') $root $planFile $ExpectedPlanSha $preflight
if ($LASTEXITCODE -ne 0) { throw 'Read-only preflight failed; nothing deleted' }
$approved = Get-Content -LiteralPath $preflight -Raw -Encoding utf8 | ConvertFrom-Json
if ($approved.status -ne 'PASS' -or $approved.plan_sha256 -ne $ExpectedPlanSha) { throw 'Invalid preflight' }
$processPaths = @(Get-CimInstance Win32_Process | ForEach-Object { if ($_.ExecutablePath) { $_.ExecutablePath } })
$targets = @()
foreach ($entry in $approved.targets) {
    $target = Resolve-SafeChild $entry.absolute_path
    if (-not $target.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Target outside workspace: $target" }
    if ($target -ine [IO.Path]::GetFullPath((Join-Path $root $entry.path)).TrimEnd('\')) { throw 'Path mismatch' }
    $cursor = $target
    while ($cursor -ine $root) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse ancestor: $cursor" }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    foreach ($protected in $proposal.protected_roots) {
        $p = [IO.Path]::GetFullPath((Join-Path $root $protected)).TrimEnd('\')
        if ($target -ieq $p -or $target.StartsWith($p+'\', [StringComparison]::OrdinalIgnoreCase) -or $p.StartsWith($target+'\', [StringComparison]::OrdinalIgnoreCase)) { throw "Protected target: $target" }
    }
    foreach ($exe in $processPaths) {
        if ($exe.StartsWith($target+'\', [StringComparison]::OrdinalIgnoreCase)) { throw "Running executable uses target: $target" }
    }
    $targets += $entry
}
if (-not $Apply) { Write-Output 'Dry run: approved; no deletion requested'; exit 0 }

$receipt = [ordered]@{status='RUNNING'; plan_sha256=$ExpectedPlanSha; workspace=$root; removed=@(); failure=$null; freed_file_bytes=[long]0; removed_file_count=[long]0}
function Save-Receipt { $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptFile -Encoding utf8 }
Save-Receipt
try {
    foreach ($entry in $targets) {
        # Recheck directory links immediately before the literal recursive delete.
        $target = Resolve-SafeChild $entry.absolute_path
        if ($target -ine [IO.Path]::GetFullPath((Join-Path $root $entry.path)).TrimEnd('\')) { throw 'Target path changed' }
        $nodes = @(Get-Item -LiteralPath $target -Force) + @(Get-ChildItem -LiteralPath $target -Force -Recurse)
        if ($nodes | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1) { throw "Reparse entry appeared: $target" }
        $files = @($nodes | Where-Object { -not $_.PSIsContainer })
        $size = [long](($files | Measure-Object -Property Length -Sum).Sum)
        if ($files.Count -ne $entry.file_count -or $size -ne $entry.size_bytes) { throw "Target changed after preflight: $target" }
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $target) { throw "Target still exists: $target" }
        $receipt.removed += $entry
        $receipt.freed_file_bytes += $entry.size_bytes
        $receipt.removed_file_count += $entry.file_count
        Save-Receipt
        if ($receipt.removed.Count % 20 -eq 0) { Write-Output "Removed $($receipt.removed.Count)/$($targets.Count) directories" }
    }
    $receipt.status = 'PASS'
} catch {
    $receipt.status = 'FAILED_PARTIAL'
    $receipt.failure = $_.Exception.Message
    throw
} finally { Save-Receipt }
Write-Output "Cleanup PASS: $($receipt.removed.Count) directories; $($receipt.freed_file_bytes) file bytes"
