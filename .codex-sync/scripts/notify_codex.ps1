# notify_codex.ps1 — α-mode helper for the Claude↔Codex sync loop.
#
# When running in --watcher-mode=manual (α mode), Codex is an interactive
# session and the user pastes between terminals by hand. This script finds the
# newest Claude sentinel the user hasn't yet pasted to Codex and copies it to
# the clipboard.
#
# Usage:   .\notify_codex.ps1
#          .\notify_codex.ps1 -PathOnly        # print path instead of copying
#          .\notify_codex.ps1 -ShowContent     # also dump content to stdout

param(
    [switch]$PathOnly,
    [switch]$ShowContent
)

$mailbox = Join-Path (Get-Location).Path '.codex-sync'
if (-not (Test-Path (Join-Path $mailbox 'status.json'))) {
    Write-Host "No .codex-sync/ in current directory. Run /claude-codex-sync-init first." -ForegroundColor Yellow
    exit 1
}

$status = Get-Content (Join-Path $mailbox 'status.json') -Raw | ConvertFrom-Json
if ($status.halted) {
    Write-Host "Mailbox is halted (reason: $($status.halt_reason)). Nothing to notify." -ForegroundColor Yellow
    exit 0
}

# Find the latest brief or APPROVE_FOR_QA review that has no matching Codex response
$briefs = Get-ChildItem (Join-Path $mailbox 'iter-*-claude-brief.md') -ErrorAction SilentlyContinue
$reviews = Get-ChildItem (Join-Path $mailbox 'iter-*-claude-review.md') -ErrorAction SilentlyContinue

$candidate = $null
$kind = $null

foreach ($b in ($briefs | Sort-Object Name)) {
    $iter = ($b.BaseName -replace 'iter-(\d+)-claude-brief', '$1')
    $execPath = Join-Path $mailbox "iter-$iter-codex-execution.md"
    if (-not (Test-Path $execPath)) {
        $candidate = $b
        $kind = "BRIEF (Codex should EXECUTE)"
        # don't break — keep going to find latest
    }
}

foreach ($r in ($reviews | Sort-Object Name)) {
    $iter = ($r.BaseName -replace 'iter-(\d+)-claude-review', '$1')
    $qaPath = Join-Path $mailbox "iter-$iter-codex-qa.md"
    if (-not (Test-Path $qaPath)) {
        # Check verdict
        $content = Get-Content $r.FullName -Raw
        if ($content -match 'verdict:\s*APPROVE_FOR_QA') {
            $candidate = $r
            $kind = "REVIEW (Codex should QA)"
        }
    }
}

if ($null -eq $candidate) {
    Write-Host "Nothing pending — Codex is caught up. Current iter: $($status.current_iteration), cycle: $($status.current_cycle)." -ForegroundColor Green
    exit 0
}

if ($PathOnly) {
    Write-Output $candidate.FullName
    exit 0
}

# Build the paste payload — same shape as what the watcher would feed
$payload = (Get-Content $candidate.FullName -Raw).TrimEnd() + "`n`n---`n`n"
if ($kind -like "BRIEF*") {
    $iterStr = ($candidate.BaseName -replace 'iter-(\d+)-claude-brief', '$1')
    $payload += "EXECUTE THIS BRIEF NOW. Stage artifacts under .codex-sync/artifacts/iter-$iterStr/. Write your execution report to .codex-sync/iter-$iterStr-codex-execution.md LAST (use .tmp + rename). Then STOP — return to Terminal A so Claude can review.`n"
} else {
    $iterStr = ($candidate.BaseName -replace 'iter-(\d+)-claude-review', '$1')
    $payload += "RUN QA NOW. Above is Claude's APPROVE_FOR_QA review with the QA checklist. Execute every item. You may fix MINOR issues per qa_scope.may_fix. Write your QA report to .codex-sync/iter-$iterStr-codex-qa.md LAST (use .tmp + rename). Verdict: PASS | MINOR_FIXED | MAJOR_ESCALATE.`n"
}

Set-Clipboard -Value $payload

Write-Host "✓ Copied to clipboard: $($candidate.Name) ($kind)" -ForegroundColor Green
Write-Host "  Path:    $($candidate.FullName)"
Write-Host "  Size:    $($payload.Length) chars"
Write-Host ""
Write-Host "Switch to your Codex terminal and paste (Ctrl+V or right-click)."

if ($ShowContent) {
    Write-Host ""
    Write-Host "─── PAYLOAD ─────────────────────────────────────────────────────────"
    Write-Output $payload
    Write-Host "─────────────────────────────────────────────────────────────────────"
}
