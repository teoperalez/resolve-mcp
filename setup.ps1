<#
.SYNOPSIS
  First-time setup for resolve-mcp: install Python deps and register the MCP server.

.DESCRIPTION
  Called automatically by bootstrap.ps1 after cloning. Also safe to run manually.
  Idempotent — re-running just re-syncs deps and re-registers the MCP server.

.PARAMETER Dest
  Absolute path to the resolve-mcp repo root. Defaults to the script's own directory.
#>
param([string]$Dest = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
$Dest = (Resolve-Path $Dest).Path

# ── 1. Ensure uv is available ─────────────────────────────────────────────────
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $uvCandidates = @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:LOCALAPPDATA\uv\bin\uv.exe"
    )
    $uvBin = $uvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($uvBin) {
        $env:PATH = "$(Split-Path $uvBin);$env:PATH"
        Write-Host "  [resolve-mcp] uv found at $uvBin" -ForegroundColor DarkGray
    } else {
        Write-Host "  [resolve-mcp] uv not found — installing..." -ForegroundColor Yellow
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    }
}
$uvExe = (Get-Command uv).Source

# ── 2. Install Python deps ────────────────────────────────────────────────────
Write-Host "  [resolve-mcp] Installing Python dependencies..." -ForegroundColor Cyan
Push-Location $Dest
try {
    & $uvExe sync --extra transcription
} finally {
    Pop-Location
}

# ── 3. Register MCP server (user scope = available in all projects) ───────────
Write-Host "  [resolve-mcp] Registering MCP server with Claude Code..." -ForegroundColor Cyan
claude mcp remove resolve 2>&1 | Out-Null
claude mcp add --scope user resolve `
    -- $uvExe --directory $Dest run resolve-mcp

Write-Host "  [resolve-mcp] Setup complete." -ForegroundColor Green
Write-Host "  [resolve-mcp] Start a new Claude Code session to activate the 'resolve' MCP server." -ForegroundColor Green
