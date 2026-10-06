<#
.SYNOPSIS
    Renders the usage-audit prompt for a project and runs or schedules it headlessly with the Claude Code CLI.
.DESCRIPTION
    Part of the IT Department skill token optimizer (workflows/efficiency-and-usage-audit.md, section 5B).
    Reads <ProjectRoot>/.it-department/config.json (efficiency block), fills the placeholders of
    templates/usage-audit-prompt.md and
      -DryRun   (default) prints the rendered prompt path, the claude command and the trigger
      -RunNow   runs one audit now:  claude -p <prompt> --model <audit_model> ... (cwd = ProjectRoot)
      -Register creates/updates a Windows Scheduled Task that calls this script with -RunNow every
                audit_interval_days at -At (default 08:30 local time)
    Prerequisites for -RunNow/-Register: the claude CLI logged in on this machine, Python 3.8+ on PATH,
    the project's transcripts in ~/.claude/projects (the audit rebuilds the ledger from them).
.PARAMETER ProjectRoot
    Target project root (holds .it-department/config.json).
.PARAMETER SkillRoot
    Installed skill package. Defaults to the parent of this script.
.PARAMETER IntervalDays
    Overrides efficiency.audit_interval_days for the trigger.
.PARAMETER At
    Local time of day for the scheduled trigger, HH:mm. Default 08:30.
.PARAMETER Model
    Overrides efficiency.audit_model.
.PARAMETER TaskName
    Scheduled task name. Default "IT-Department usage audit - <project_name>".
.PARAMETER ClaudeExe
    Path or name of the claude CLI. Default "claude".
#>
[CmdletBinding(DefaultParameterSetName = 'DryRun')]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [string]$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [Parameter(ParameterSetName = 'DryRun')]
    [switch]$DryRun,

    [Parameter(ParameterSetName = 'RunNow')]
    [switch]$RunNow,

    [Parameter(ParameterSetName = 'Register')]
    [switch]$Register,

    [int]$IntervalDays = 0,
    [string]$At = "08:30",
    [string]$Model = "",
    [string]$TaskName = "",
    [string]$ClaudeExe = "claude"
)

$ErrorActionPreference = "Stop"

# --- 1. Resolve inputs -------------------------------------------------------------------------------------
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$SkillRoot = [System.IO.Path]::GetFullPath($SkillRoot)
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "ProjectRoot not found: $ProjectRoot" }
$configPath = Join-Path $ProjectRoot ".it-department\config.json"
if (-not (Test-Path -LiteralPath $configPath)) { throw "Missing $configPath - run init-project first." }
$templatePath = Join-Path $SkillRoot "templates\usage-audit-prompt.md"
if (-not (Test-Path -LiteralPath $templatePath)) { throw "Skill package error: $templatePath not found." }

$cfg = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8 | ConvertFrom-Json
$eff = $cfg.efficiency
if (-not $eff) {
    Write-Warning "config.json has no 'efficiency' block - using defaults (copy it from assets/config-template.json to tune)."
    $eff = [pscustomobject]@{}
}
function Get-Setting($obj, [string]$name, $default) {
    if ($null -ne $obj -and $null -ne $obj.PSObject.Properties[$name] -and $null -ne $obj.$name -and "$($obj.$name)" -ne "") { return $obj.$name }
    return $default
}
$interval = if ($IntervalDays -gt 0) { $IntervalDays } else { [int](Get-Setting $eff "audit_interval_days" 2) }
$model = if ($Model) { $Model } else { [string](Get-Setting $eff "audit_model" "claude-fable-5-1") }
$language = [string](Get-Setting $eff "report_language" "en")
$ledgerPath = [string](Get-Setting $eff "ledger_path" ".it-department/sessions/_usage/ledger")
$reportsPath = [string](Get-Setting $eff "reports_path" "vault/05-Reports")
$vaultPath = [string](Get-Setting $cfg.paths "vault_relative_path" "vault")
$branch = [string](Get-Setting $cfg.git_policy "integration_branch" "development")
$projectName = [string](Get-Setting $cfg "project_name" (Split-Path -Leaf $ProjectRoot))
if (-not $TaskName) { $TaskName = "IT-Department usage audit - $projectName" }
if ($At -notmatch '^\d{1,2}:\d{2}$') { throw "-At must be HH:mm, got '$At'" }

# --- 2. Render the prompt from the template ----------------------------------------------------------------
$template = Get-Content -Raw -LiteralPath $templatePath -Encoding UTF8
$m = [regex]::Match($template, '(?s)```text\r?\n(.*?)\r?\n```')
if (-not $m.Success) { throw "Could not find the prompt block (```text fence) in $templatePath" }
$prompt = $m.Groups[1].Value
$refresh = "Run ``python3 {SKILL_ROOT}/scripts/usage_ledger.py --root {PROJECT_ROOT}`` (``python`` on Windows); it reads this project's transcripts from ~/.claude/projects and rewrites ``{PROJECT_ROOT}/{LEDGER_PATH}`` (idempotent)."
$prompt = $prompt.Replace('{LEDGER_REFRESH_STEP}', $refresh)
$pr = $ProjectRoot.Replace('\', '/')
$sr = $SkillRoot.Replace('\', '/')
$map = [ordered]@{
    '{PROJECT_NAME}' = $projectName; '{PROJECT_ROOT}' = $pr; '{SKILL_ROOT}' = $sr
    '{INTEGRATION_BRANCH}' = $branch; '{VAULT_PATH}' = $vaultPath; '{LEDGER_PATH}' = $ledgerPath
    '{REPORTS_PATH}' = $reportsPath; '{AUDIT_INTERVAL_DAYS}' = "$interval"; '{REPORT_LANGUAGE}' = $language
}
foreach ($k in $map.Keys) { $prompt = $prompt.Replace($k, [string]$map[$k]) }
$prompt = $prompt.Replace('python3 ', 'python ')   # Windows interpreter name
$leftover = [regex]::Matches($prompt, '\{[A-Z_]+\}') | ForEach-Object { $_.Value } | Sort-Object -Unique
if ($leftover) { throw "Unfilled placeholders in the prompt: $($leftover -join ', ')" }

$usageDir = Join-Path $ProjectRoot ($ledgerPath.Replace('/', '\'))
$usageDir = Split-Path -Parent $usageDir            # <sessions>/_usage
$runsDir = Join-Path $usageDir "audit-runs"
$promptPath = Join-Path $usageDir "audit-prompt.generated.md"
New-Item -ItemType Directory -Force -Path $usageDir, $runsDir | Out-Null
Set-Content -LiteralPath $promptPath -Value $prompt -Encoding UTF8 -NoNewline

# --- 3. The headless command -------------------------------------------------------------------------------
$allowedTools = @(
    'Read', 'Write', 'Edit', 'MultiEdit', 'Glob', 'Grep',
    'Bash(python *)', 'Bash(python3 *)', 'Bash(py *)',
    'Bash(git add *)', 'Bash(git commit *)', 'Bash(git status *)', 'Bash(git log *)', 'Bash(git diff *)', 'Bash(git rev-parse *)', 'Bash(git branch *)',
    'Bash(ls *)', 'Bash(cat *)', 'Bash(dir *)'
) -join ' '
$claudeArgs = @('-p', '--model', $model, '--permission-mode', 'acceptEdits', '--allowedTools', $allowedTools,
                '--add-dir', $SkillRoot, '--output-format', 'text')
$displayCmd = "$ClaudeExe " + (($claudeArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ') + " < `"$promptPath`""

Write-Host "==> IT Department usage audit (headless)"
Write-Host "    Project:   $ProjectRoot ($projectName)"
Write-Host "    Skill:     $SkillRoot"
Write-Host "    Model:     $model   Interval: every $interval day(s) at $At   Language: $language"
Write-Host "    Prompt:    $promptPath"
Write-Host "    Command:   $displayCmd"
Write-Host "    Logs:      $runsDir"

switch ($PSCmdlet.ParameterSetName) {
    'RunNow' {
        $claude = Get-Command $ClaudeExe -ErrorAction SilentlyContinue
        if (-not $claude) { throw "claude CLI not found ('$ClaudeExe'). Install Claude Code or pass -ClaudeExe." }
        $logPath = Join-Path $runsDir ("{0}.log" -f (Get-Date -Format 'yyyy-MM-dd_HHmmss'))
        Write-Host "==> Running audit now; output -> $logPath"
        Push-Location -LiteralPath $ProjectRoot
        try {
            $prompt | & $claude.Source @claudeArgs 2>&1 | Tee-Object -FilePath $logPath
            $code = $LASTEXITCODE
        } finally { Pop-Location }
        if ($code -ne 0) { throw "claude exited with code $code (see $logPath)" }
        Write-Host "==> Audit finished; report under $reportsPath"
    }
    'Register' {
        if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core' -and $env:OS -ne 'Windows_NT') {
            throw "-Register uses the Windows Task Scheduler; on Linux/macOS use scripts/schedule-usage-audit.sh --register"
        }
        $pwsh = (Get-Process -Id $PID).Path
        $scriptPath = $MyInvocation.MyCommand.Path
        $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`" -SkillRoot `"$SkillRoot`" -RunNow" +
                   $(if ($Model) { " -Model `"$Model`"" } else { "" }) + $(if ($ClaudeExe -ne 'claude') { " -ClaudeExe `"$ClaudeExe`"" } else { "" })
        $action = New-ScheduledTaskAction -Execute $pwsh -Argument $argLine -WorkingDirectory $ProjectRoot
        $trigger = New-ScheduledTaskTrigger -Daily -DaysInterval $interval -At $At
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host "==> Scheduled task '$TaskName' registered: every $interval day(s) at $At, next run $($info.NextRunTime)."
        Write-Host "    Keep efficiency.audit_interval_days in config.json equal to $interval. Remove with: Unregister-ScheduledTask -TaskName `"$TaskName`""
    }
    default {
        Write-Host "==> Dry run only. Use -RunNow to audit now or -Register to schedule (Windows Task Scheduler: daily trigger, DaysInterval=$interval, $At)."
    }
}
