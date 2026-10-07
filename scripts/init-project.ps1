<#
.SYNOPSIS
    Idempotent project initialization script for the IT Department skill.
.DESCRIPTION
    Initializes a target project workspace with the project-local vault, configuration,
    and runtime directories. Validates paths before filesystem mutation.
    Preserves existing files, configurations, and user notes.
.PARAMETER ProjectRoot
    The target project's root directory containing its workspace/repository.
.PARAMETER SkillRoot
    The path to the installed it-department-skill package. Defaults to the parent of this script.
.PARAMETER ProjectName
    Optional project name. Defaults to the directory name of ProjectRoot.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $false)]
    [string]$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [Parameter(Mandatory = $false)]
    [string]$ProjectName
)

$ErrorActionPreference = "Stop"

function Get-CanonicalPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path cannot be empty or whitespace."
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $fullPath) {
        $item = Get-Item -LiteralPath $fullPath -Force
        if ($item.LinkType -and $item.Target) {
            $target = if ($item.Target -is [array]) { $item.Target[0] } else { $item.Target }
            if ($target) {
                return [System.IO.Path]::GetFullPath($target)
            }
        }
        return (Resolve-Path -LiteralPath $fullPath).ProviderPath
    }
    # Path does not exist yet; resolve through existing ancestor
    $parent = [System.IO.Path]::GetDirectoryName($fullPath)
    $leaf = [System.IO.Path]::GetFileName($fullPath)
    while ($parent -and -not (Test-Path -LiteralPath $parent)) {
        $leaf = [System.IO.Path]::Combine([System.IO.Path]::GetFileName($parent), $leaf)
        $parent = [System.IO.Path]::GetDirectoryName($parent)
    }
    if ($parent -and (Test-Path -LiteralPath $parent)) {
        $item = Get-Item -LiteralPath $parent -Force
        $resolvedParent = if ($item.LinkType -and $item.Target) {
            $target = if ($item.Target -is [array]) { $item.Target[0] } else { $item.Target }
            [System.IO.Path]::GetFullPath($target)
        } else {
            (Resolve-Path -LiteralPath $parent).ProviderPath
        }
        return [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($resolvedParent, $leaf))
    }
    return $fullPath
}

function Split-PathSegments([string]$Path) {
    return $Path.TrimEnd('\', '/').Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
}

function Test-IsSameOrInside([string]$Child, [string]$Parent) {
    $cParts = Split-PathSegments $Child
    $pParts = Split-PathSegments $Parent
    if ($cParts.Length -lt $pParts.Length) { return $false }
    for ($i = 0; $i -lt $pParts.Length; $i++) {
        if (-not [string]::Equals($cParts[$i], $pParts[$i], [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }
    return $true
}

function Test-IsStrictInside([string]$Child, [string]$Parent) {
    $cParts = Split-PathSegments $Child
    $pParts = Split-PathSegments $Parent
    if ($cParts.Length -le $pParts.Length) { return $false }
    for ($i = 0; $i -lt $pParts.Length; $i++) {
        if (-not [string]::Equals($cParts[$i], $pParts[$i], [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }
    return $true
}

function Assert-ValidRelativePath([string]$RelativePath, [string]$Field, [string]$ProjectRoot, [string]$SkillRoot) {
    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw "Configuration path '$Field' must not be empty or whitespace."
    }
    if ([System.IO.Path]::IsPathRooted($RelativePath)) {
        throw "Configuration path '$Field' must be a relative path, got absolute path: '$RelativePath'"
    }
    $combined = [System.IO.Path]::Combine($ProjectRoot, $RelativePath)
    $resolved = [System.IO.Path]::GetFullPath($combined)
    if (-not (Test-IsStrictInside $resolved $ProjectRoot)) {
        throw "Configuration path '$Field' ('$RelativePath') resolves outside project root: '$resolved'"
    }
    if (Test-IsSameOrInside $resolved $SkillRoot) {
        throw "Configuration path '$Field' ('$RelativePath') resolves inside skill root: '$resolved'"
    }
    return $resolved
}

# UTF-8 without BOM and with the content's own line endings (Set-Content adds a BOM in Windows PowerShell 5.1)
function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding $false))
}

# --- 1. Validate & Canonicalize Roots BEFORE Filesystem Mutation ---
$canonicalSkillRoot = Get-CanonicalPath $SkillRoot
$canonicalProjectRoot = Get-CanonicalPath $ProjectRoot

if (Test-IsSameOrInside $canonicalProjectRoot $canonicalSkillRoot) {
    throw "Invalid ProjectRoot: Project root ('$canonicalProjectRoot') cannot be equal to or located inside skill root ('$canonicalSkillRoot')."
}
if (Test-IsSameOrInside $canonicalSkillRoot $canonicalProjectRoot) {
    # A skill installed inside the project is fine when it sits in a standard skills folder
    # (<project>/.agents/skills/<name> or <project>/.claude/skills/<name>, e.g. via `npx skills add`).
    $skillParent = Split-Path -Parent $canonicalSkillRoot
    $skillGrand = if ($skillParent) { Split-Path -Parent $skillParent } else { "" }
    $inSkillsFolder = $skillParent -and $skillGrand -and ((Split-Path -Leaf $skillParent) -eq "skills") -and ((Split-Path -Leaf $skillGrand) -in @(".agents", ".claude"))
    if (-not $inSkillsFolder) {
        throw "Invalid ProjectRoot: Skill root ('$canonicalSkillRoot') cannot be located inside project root ('$canonicalProjectRoot') unless it is under <project>/.agents/skills/ or <project>/.claude/skills/."
    }
}

$vaultTemplateDir = Join-Path $canonicalSkillRoot "assets/vault-template"
$configTemplatePath = Join-Path $canonicalSkillRoot "assets/config-template.json"
$schemaTemplatePath = Join-Path $canonicalSkillRoot "assets/project-config.schema.json"

if (-not (Test-Path -LiteralPath $vaultTemplateDir)) {
    throw "Skill package error: Vault template directory not found at '$vaultTemplateDir'"
}
if (-not (Test-Path -LiteralPath $configTemplatePath)) {
    throw "Skill package error: Config template not found at '$configTemplatePath'"
}
if (-not (Test-Path -LiteralPath $schemaTemplatePath)) {
    throw "Skill package error: Schema template not found at '$schemaTemplatePath'"
}

if ([string]::IsNullOrWhiteSpace($ProjectName)) {
    $ProjectName = [System.IO.Path]::GetFileName($canonicalProjectRoot)
    if ([string]::IsNullOrWhiteSpace($ProjectName)) {
        $ProjectName = "Project Workspace"
    }
}

# Fixed configuration location: <project_root>/.it-department/config.json
$projectRuntimeDir = Join-Path $canonicalProjectRoot ".it-department"
$projectConfigPath = Join-Path $projectRuntimeDir "config.json"
$projectSchemaPath = Join-Path $projectRuntimeDir "project-config.schema.json"

# --- 2. Load or Prepare Configuration ---
$isNewConfig = -not (Test-Path -LiteralPath $projectConfigPath)
$configObj = $null

if ($isNewConfig) {
    $rawTemplate = Get-Content -Raw -LiteralPath $configTemplatePath -Encoding UTF8
    $configObj = ConvertFrom-Json $rawTemplate
    $configObj.project_name = [string]$ProjectName
    # A new project's profile review is dated today (template placeholder {YYYY-MM-DD}); existing configs are never touched
    $reviewObj = if ($configObj.PSObject.Properties['profile_review']) { $configObj.profile_review } else { $null }
    if ($reviewObj -is [System.Management.Automation.PSCustomObject] -and $reviewObj.PSObject.Properties['reviewed_at'] -and
        $reviewObj.reviewed_at -is [string] -and $reviewObj.reviewed_at -ceq '{YYYY-MM-DD}') {
        $reviewObj.reviewed_at = (Get-Date).ToString("yyyy-MM-dd")
    }
} else {
    try {
        $rawExisting = Get-Content -Raw -LiteralPath $projectConfigPath -Encoding UTF8
        $configObj = ConvertFrom-Json $rawExisting
    } catch {
        throw "Existing configuration at '$projectConfigPath' is invalid JSON: $_"
    }
    if (-not $configObj.paths) {
        throw "Existing configuration at '$projectConfigPath' is missing required 'paths' section."
    }
}

# --- 3. Validate All Configured Paths BEFORE Mutation ---
$vaultRelPath = $configObj.paths.vault_relative_path
$sessionsRelPath = $configObj.paths.sessions_relative_path
$worktreesRelPath = $configObj.paths.worktrees_relative_path

$resolvedVaultDir = Assert-ValidRelativePath $vaultRelPath "paths.vault_relative_path" $canonicalProjectRoot $canonicalSkillRoot
$resolvedSessionsDir = Assert-ValidRelativePath $sessionsRelPath "paths.sessions_relative_path" $canonicalProjectRoot $canonicalSkillRoot
$resolvedWorktreesDir = Assert-ValidRelativePath $worktreesRelPath "paths.worktrees_relative_path" $canonicalProjectRoot $canonicalSkillRoot

# Token optimizer: usage ledger directory (efficiency.ledger_path, default under the sessions directory)
$hasEfficiency = [bool]($configObj.PSObject.Properties['efficiency'] -and $configObj.efficiency)
$ledgerRelPath = if ($hasEfficiency -and -not [string]::IsNullOrWhiteSpace($configObj.efficiency.ledger_path)) {
    [string]$configObj.efficiency.ledger_path
} else {
    ".it-department/sessions/_usage/ledger"
}
$resolvedLedgerDir = Assert-ValidRelativePath $ledgerRelPath "efficiency.ledger_path" $canonicalProjectRoot $canonicalSkillRoot
$resolvedUsageDir = Split-Path -Parent $resolvedLedgerDir

# Content review: locales used to fill the glossary / style guide placeholders of the vault template
$crCfg = if ($configObj.PSObject.Properties['content_review']) { $configObj.content_review } else { $null }
$contentSourceLocale = if ($crCfg -and -not [string]::IsNullOrWhiteSpace([string]$crCfg.source_locale)) { [string]$crCfg.source_locale } else { "en" }
$contentLocales = if ($crCfg -and $crCfg.locales) { (@($crCfg.locales) -join ", ") } else { $contentSourceLocale }

# --- 4. Mutate Filesystem Safely & Idempotently ---
Write-Host "==> Initializing IT Department for Project: $($configObj.project_name)"
Write-Host "    Project Root: $canonicalProjectRoot"
Write-Host "    Skill Root:   $canonicalSkillRoot"

if (-not (Test-Path -LiteralPath $projectRuntimeDir)) {
    $null = New-Item -ItemType Directory -Force -Path $projectRuntimeDir
}
# Runtime data shared through the project folder but never committed (lock, worktrees, raw usage, dated hand-offs)
$runtimeGitignore = Join-Path $projectRuntimeDir ".gitignore"
if (-not (Test-Path -LiteralPath $runtimeGitignore)) {
    $runtimeIgnoreLines = @(
        "lock.json",
        "worktrees/",
        "sessions/_usage/raw/",
        "sessions/_usage/audit-runs/",
        "sessions/_usage/audit-prompt.generated.md",
        "sessions/_handoff/*",
        "!sessions/_handoff/latest.md"
    )
    Write-Utf8NoBom $runtimeGitignore (($runtimeIgnoreLines -join "`n") + "`n")
}
if (-not (Test-Path -LiteralPath $resolvedSessionsDir)) {
    $null = New-Item -ItemType Directory -Force -Path $resolvedSessionsDir
}
if (-not (Test-Path -LiteralPath $resolvedWorktreesDir)) {
    $null = New-Item -ItemType Directory -Force -Path $resolvedWorktreesDir
}
if (-not (Test-Path -LiteralPath $resolvedLedgerDir)) {
    $null = New-Item -ItemType Directory -Force -Path $resolvedLedgerDir
}
$usageGitignore = Join-Path $resolvedUsageDir ".gitignore"
if (-not (Test-Path -LiteralPath $usageGitignore)) {
    $gitignoreLines = @(
        "# IT Department usage ledger: keep ledger/*.json (aggregates only); ignore raw transcript copies and audit runs",
        "raw/",
        "audit-runs/",
        "audit-prompt.generated.md"
    )
    Set-Content -LiteralPath $usageGitignore -Value ($gitignoreLines -join "`n") -Encoding UTF8
}

# Copy schema definition into project runtime dir if absent
if (-not (Test-Path -LiteralPath $projectSchemaPath)) {
    Copy-Item -LiteralPath $schemaTemplatePath -Destination $projectSchemaPath -Force
}

# Write config.json if new, using structured serialization
if ($isNewConfig) {
    Write-Host "    Writing .it-department/config.json with structured JSON serialization..."
    $serializedConfig = ConvertTo-Json $configObj -Depth 10
    Set-Content -LiteralPath $projectConfigPath -Value $serializedConfig -Encoding UTF8
} else {
    Write-Host "    Preserving existing .it-department/config.json."
}

# Initialize configured vault idempotently
Write-Host "    Synchronizing vault at: $resolvedVaultDir"
if (-not (Test-Path -LiteralPath $resolvedVaultDir)) {
    $null = New-Item -ItemType Directory -Force -Path $resolvedVaultDir
}

$templateItems = Get-ChildItem -LiteralPath $vaultTemplateDir -Recurse

foreach ($item in $templateItems) {
    $relativePath = $item.FullName.Substring($vaultTemplateDir.Length).TrimStart('\', '/')
    $targetItemPath = Join-Path $resolvedVaultDir $relativePath

    if ($item.PSIsContainer) {
        if (-not (Test-Path -LiteralPath $targetItemPath)) {
            $null = New-Item -ItemType Directory -Force -Path $targetItemPath
        }
    } else {
        if (-not (Test-Path -LiteralPath $targetItemPath)) {
            if ($item.Name -eq "00-Dashboard.md") {
                $dashContent = Get-Content -Raw -LiteralPath $item.FullName -Encoding UTF8
                $currentDate = (Get-Date).ToString("yyyy-MM-dd")
                $effectiveName = [string]$configObj.project_name
                $effectiveCtoMode = if ($configObj.cto_mode) { [string]$configObj.cto_mode } else { "VIRTUAL" }
                $dashContent = $dashContent -replace '\{PROJECT_NAME\}', [System.Text.RegularExpressions.Regex]::Escape($effectiveName).Replace('\', '\\')
                $dashContent = $dashContent.Replace([System.Text.RegularExpressions.Regex]::Escape($effectiveName).Replace('\', '\\'), $effectiveName)
                $dashContent = $dashContent -replace '\{LAST_UPDATED\}', $currentDate
                $dashContent = $dashContent -replace '\{CTO_MODE\}', $effectiveCtoMode
                Set-Content -LiteralPath $targetItemPath -Value $dashContent -Encoding UTF8
            } elseif ($relativePath -like "06-Content*") {
                $contentDoc = Get-Content -Raw -LiteralPath $item.FullName -Encoding UTF8
                $contentDoc = $contentDoc.Replace('{SOURCE_LOCALE}', $contentSourceLocale).Replace('{LOCALES}', $contentLocales).Replace('{DATE}', (Get-Date).ToString("yyyy-MM-dd"))
                Set-Content -LiteralPath $targetItemPath -Value $contentDoc -Encoding UTF8
            } elseif (($relativePath -replace '\\', '/') -eq "03-ADR/decisions-log.md") {
                $journalDoc = Get-Content -Raw -LiteralPath $item.FullName -Encoding UTF8
                $journalDoc = $journalDoc.Replace('{PROJECT_NAME}', [string]$configObj.project_name).Replace('{DATE}', (Get-Date).ToString("yyyy-MM-dd"))
                Write-Utf8NoBom $targetItemPath $journalDoc
            } else {
                Copy-Item -LiteralPath $item.FullName -Destination $targetItemPath -Force
            }
        }
    }
}

Write-Host "==> Initialization completed successfully."
Write-Host "    Vault:     $resolvedVaultDir"
Write-Host "    Sessions:  $resolvedSessionsDir"
Write-Host "    Worktrees: $resolvedWorktreesDir"
Write-Host "    Ledger:    $resolvedLedgerDir"
$activeProfile = if ($configObj.PSObject.Properties['operating_profile']) { [string]$configObj.operating_profile } else { "" }
if (-not [string]::IsNullOrWhiteSpace($activeProfile)) {
    Write-Host "    Profile:   $activeProfile (workflows/operating-profiles.md)"
} else {
    Write-Host "    Profile:   production (config.json has no operating_profile; workflows/operating-profiles.md)"
}
if (-not $hasEfficiency) {
    Write-Host "    [HINT] config.json has no 'efficiency' block: the token optimizer uses default limits and paths. Copy the block from '$configTemplatePath' to tune rules R1-R5 and the audit interval."
}
