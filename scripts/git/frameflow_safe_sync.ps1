[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Get-Location).Path,
    [string]$Remote = "origin",
    [string[]]$Path,
    [string]$CommitMessage = "chore: safe sync",
    [string]$LogPath
)

$ErrorActionPreference = "Stop"

function Invoke-GitText {
    param([string[]]$GitArgs)
    $output = & git -C $script:RepoRoot @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $detail = ($output -join "`n").Trim()
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "git exit code $LASTEXITCODE" }
        throw $detail
    }
    return ($output -join "`n").Trim()
}

function Invoke-GitNoOutput {
    param([string[]]$GitArgs)
    $allArgs = @("-C", $script:RepoRoot) + $GitArgs
    $argumentLine = (($allArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " ")
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath "git.exe" -ArgumentList $argumentLine -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    } finally {
        Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
    if ($process.ExitCode -ne 0) {
        throw "git operation failed with exit code $($process.ExitCode)"
    }
}

function Redact-Log {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    return ($Value -replace '(?i)(api[_-]?key|authorization|cookie|password|secret|token)(\s*[:=]\s*)[^\s,;]+', '$1$2[REDACTED]')
}

function Write-SyncLog {
    param([string]$Message)
    if ([string]::IsNullOrWhiteSpace($script:LogPath)) { return }
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString("o"), (Redact-Log $Message)
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
}

function Test-ProtectedPath {
    param([string]$RelativePath)
    $normalized = $RelativePath.Replace("\", "/")
    if ($normalized -match '(?i)(^|/)(\.env($|\.)|.*\.pem$|.*\.key$|.*\.p12$|.*\.pfx$)') { return $true }
    if ($normalized -match '(?i)(^|/)(data/.*\.db$|.*\.sqlite$|.*\.sqlite3$|backups?/|generated/|pytest-cache-files/|node_modules/|\.venv/)') { return $true }
    if ($normalized -match '(?i)\.(zip|7z|rar|tar|gz|mp4|mov|mkv|wav|flac)$') { return $true }
    $absolute = Join-Path $script:RepoRoot $normalized
    if (Test-Path -LiteralPath $absolute -PathType Leaf) {
        $length = (Get-Item -LiteralPath $absolute).Length
        if ($length -gt 104857600) { return $true }
    }
    return $false
}

$script:RepoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$gitDirRaw = Invoke-GitText @("rev-parse", "--git-dir")
$gitDir = if ([IO.Path]::IsPathRooted($gitDirRaw)) { $gitDirRaw } else { Join-Path $script:RepoRoot $gitDirRaw }
$script:LogPath = if ([string]::IsNullOrWhiteSpace($LogPath)) { Join-Path $gitDir "frameflow-safe-sync.log" } else { $LogPath }
$logParent = Split-Path -Parent $script:LogPath
if (-not [string]::IsNullOrWhiteSpace($logParent)) { New-Item -ItemType Directory -Path $logParent -Force | Out-Null }

try {
    $currentBranch = (Invoke-GitText @("branch", "--show-current")).Trim()
    $headBefore = (Invoke-GitText @("rev-parse", "HEAD")).Trim()
    Write-SyncLog "repo=$script:RepoRoot branch=$currentBranch head_before=$headBefore"

    if ([string]::IsNullOrWhiteSpace($currentBranch)) {
        Write-SyncLog "status=ABORT reason=detached_head"
        throw "ABORT SAFE: detached HEAD"
    }

    $markerPaths = @("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "BISECT_HEAD")
    foreach ($marker in $markerPaths) {
        if (Test-Path -LiteralPath (Join-Path $gitDir $marker)) {
            Write-SyncLog "status=ABORT reason=in_progress_operation marker=$marker"
            throw "ABORT SAFE: repository operation marker $marker"
        }
    }
    foreach ($directory in @("rebase-merge", "rebase-apply")) {
        if (Test-Path -LiteralPath (Join-Path $gitDir $directory)) {
            Write-SyncLog "status=ABORT reason=in_progress_operation marker=$directory"
            throw "ABORT SAFE: repository operation marker $directory"
        }
    }

    $unmerged = Invoke-GitText @("diff", "--name-only", "--diff-filter=U")
    if (-not [string]::IsNullOrWhiteSpace($unmerged)) {
        Write-SyncLog "status=ABORT reason=unmerged_files"
        throw "ABORT SAFE: unmerged files"
    }

    $preStaged = Invoke-GitText @("diff", "--cached", "--name-only")
    if (-not [string]::IsNullOrWhiteSpace($preStaged)) {
        Write-SyncLog "status=ABORT reason=preexisting_staged_changes"
        throw "ABORT SAFE: pre-existing staged changes require an explicit review"
    }

    $stagePaths = if ($null -eq $Path -or $Path.Count -eq 0) { @(".") } else { $Path }
    $statusArgs = @("status", "--porcelain=1", "--untracked-files=all", "--") + $stagePaths
    $statusBefore = Invoke-GitText $statusArgs
    $statusLines = @($statusBefore -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($statusLines.Count -eq 0) {
        Write-SyncLog "status=NO_CHANGES commit_created=no push_attempted=no head_after=$headBefore"
        Write-Output "NO_CHANGES"
        exit 0
    }
    Write-SyncLog "status=DIRTY changed_entries=$($statusLines.Count)"

    foreach ($line in $statusLines) {
        if ($line.Length -lt 4) { continue }
        $relative = $line.Substring(3).Trim()
        if ($relative.Contains(" -> ")) { $relative = $relative.Split(" -> ")[-1] }
        if (Test-ProtectedPath $relative) {
            Write-SyncLog "status=ABORT reason=protected_path path=$relative"
            throw "ABORT SAFE: protected or oversized path $relative"
        }
    }

    $addArgs = @("add", "--") + $stagePaths
    Invoke-GitNoOutput $addArgs
    $staged = Invoke-GitText @("diff", "--cached", "--name-only")
    if ([string]::IsNullOrWhiteSpace($staged)) {
        Write-SyncLog "status=NO_CHANGES commit_created=no push_attempted=no head_after=$headBefore"
        Write-Output "NO_CHANGES"
        exit 0
    }
    foreach ($relative in @($staged -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        if (Test-ProtectedPath $relative.Trim()) {
            Write-SyncLog "status=ABORT reason=protected_staged_path path=$relative"
            throw "ABORT SAFE: protected path staged $relative"
        }
    }

    Invoke-GitNoOutput @("commit", "-m", $CommitMessage)
    $headAfter = (Invoke-GitText @("rev-parse", "HEAD")).Trim()
    Write-SyncLog "status=COMMITTED commit_created=yes head_after=$headAfter push_attempted=no"

    $null = Invoke-GitText @("remote", "get-url", $Remote)
    try {
        Invoke-GitNoOutput @("push", $Remote, $currentBranch)
    } catch {
        $pushErrorMessage = $_.Exception.Message
        Write-SyncLog "push_attempted=yes push_result=FAIL remote=$Remote branch=$currentBranch"
        throw ("FAIL SAFE: push failed; local commit {0} was not rewritten; details: {1}" -f $headAfter, (Redact-Log $pushErrorMessage))
    }
    Write-SyncLog "push_attempted=yes push_result=PASS remote=$Remote branch=$currentBranch"
    Write-Output "SYNC PASS: branch=$currentBranch head=$headAfter"
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-SyncLog "status=ABORT reason=$message"
    Write-Output $message
    exit 1
}
