<#
.SYNOPSIS
    Comprehensive project validation script for the IT Department skill.
.DESCRIPTION
    Validates that a project workspace conforms to the IT department layout,
    strictly validates configuration types, enums, path containment, and
    directory structures at resolved configured paths.
.PARAMETER ProjectRoot
    The target project's root directory.
.PARAMETER SkillRoot
    The path to the installed skill package.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $false)]
    [string]$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$failures = @()

function Get-CanonicalPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path cannot be empty or whitespace."
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $fullPath) {
        $item = Get-Item -LiteralPath $fullPath -Force
        if ($item.LinkType -and $item.Target) {
            $target = if ($item.Target -is [array]) { $item.Target[0] } else { $item.Target }
            if ($target) { return [System.IO.Path]::GetFullPath($target) }
        }
        return (Resolve-Path -LiteralPath $fullPath).ProviderPath
    }
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

# Python 3.8+ for scripts/vault_lint.py. The Microsoft Store "python" alias is a stub that exits non-zero with
# "Python was not found", so a candidate counts only when "--version" exits 0 and reports Python 3.8 or newer.
function Find-Python {
    foreach ($candidate in @(@('python'), @('python3'), @('py', '-3'))) {
        if (-not (Get-Command $candidate[0] -CommandType Application -ErrorAction SilentlyContinue)) { continue }
        $extraArgs = @($candidate | Select-Object -Skip 1)
        $previousPreference = $ErrorActionPreference
        $versionText = ''
        $exitCode = 1
        try {
            $ErrorActionPreference = 'Continue'
            $versionText = (& $candidate[0] @extraArgs --version 2>&1 | ForEach-Object { "$_" }) -join ' '
            $exitCode = $LASTEXITCODE
        } catch {
            $exitCode = 1
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($exitCode -eq 0 -and $versionText -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 8) {
            return ,$candidate
        }
    }
    return $null
}

$canonicalSkillRoot = Get-CanonicalPath $SkillRoot
$canonicalProjectRoot = Get-CanonicalPath $ProjectRoot

Write-Host "==> Validating IT Department Project Setup"
$skillVersionFile = Join-Path $canonicalSkillRoot "VERSION"
$skillVersion = if (Test-Path -LiteralPath $skillVersionFile) { (Get-Content -Raw -LiteralPath $skillVersionFile).Trim() } else { "unknown" }
Write-Host "    Skill version: $skillVersion (update: scripts/update-skill.ps1 -Check)"
Write-Host "    Project Root: $canonicalProjectRoot"
Write-Host "    Skill Root:   $canonicalSkillRoot"

# Boundary check: ProjectRoot must not be equal to or inside SkillRoot
if (Test-IsSameOrInside $canonicalProjectRoot $canonicalSkillRoot) {
    $failures += "Project root ('$canonicalProjectRoot') cannot be equal to or inside skill root ('$canonicalSkillRoot')."
}
if (Test-IsSameOrInside $canonicalSkillRoot $canonicalProjectRoot) {
    # Allowed inside the project only in a standard skills folder (<project>/.agents/skills/<name>, <project>/.claude/skills/<name>)
    $skillParent = Split-Path -Parent $canonicalSkillRoot
    $skillGrand = if ($skillParent) { Split-Path -Parent $skillParent } else { "" }
    $inSkillsFolder = $skillParent -and $skillGrand -and ((Split-Path -Leaf $skillParent) -eq "skills") -and ((Split-Path -Leaf $skillGrand) -in @(".agents", ".claude"))
    if (-not $inSkillsFolder) {
        $failures += "Skill root ('$canonicalSkillRoot') cannot be inside project root ('$canonicalProjectRoot') unless it is under <project>/.agents/skills/ or <project>/.claude/skills/."
    }
}

# 1. Validate Project Runtime Configuration
$configPath = Join-Path $canonicalProjectRoot ".it-department/config.json"
$configObj = $null

if (-not (Test-Path -LiteralPath $configPath)) {
    $failures += "Missing configuration file: .it-department/config.json"
} else {
    try {
        $rawConfig = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8
        $configObj = ConvertFrom-Json $rawConfig
        
        # Schema version
        if ($configObj.schema_version -ne "2.0.0") {
            $failures += "Invalid or unsupported schema_version: '$($configObj.schema_version)'. Expected '2.0.0'."
        }

        # Project name
        if ([string]::IsNullOrWhiteSpace($configObj.project_name)) {
            $failures += "Config missing or empty 'project_name'."
        }

        # CTO Mode
        if ($configObj.cto_mode -notin @("VIRTUAL", "USER")) {
            $failures += "Invalid cto_mode: '$($configObj.cto_mode)'. Allowed modes are 'VIRTUAL' or 'USER'."
        }

        # Delegated authorities
        if (-not $configObj.delegated_authorities) {
            $failures += "Config missing 'delegated_authorities' section."
        } else {
            $authKeys = @(
                "allow_merge_integration",
                "allow_merge_production",
                "allow_deploy_production",
                "allow_infra_provisioning",
                "allow_destructive_operations",
                "allow_schema_migrations",
                "allow_dependency_updates"
            )
            foreach ($k in $authKeys) {
                $val = $configObj.delegated_authorities.$k
                if ($null -eq $val -or ($val -isnot [bool] -and $val -ne $true -and $val -ne $false)) {
                    $failures += "Field 'delegated_authorities.$k' must be a boolean (true/false), got: '$val'."
                }
            }
        }

        # Git policy
        if (-not $configObj.git_policy) {
            $failures += "Config missing 'git_policy' section."
        } else {
            if ([string]::IsNullOrWhiteSpace($configObj.git_policy.production_branch)) {
                $failures += "git_policy missing valid 'production_branch'."
            }
            if ([string]::IsNullOrWhiteSpace($configObj.git_policy.integration_branch)) {
                $failures += "git_policy missing valid 'integration_branch'."
            }
            if (-not $configObj.git_policy.branch_naming_patterns) {
                $failures += "git_policy missing 'branch_naming_patterns'."
            } else {
                foreach ($bp in @("feature", "bug", "hotfix")) {
                    if ([string]::IsNullOrWhiteSpace($configObj.git_policy.branch_naming_patterns.$bp)) {
                        $failures += "git_policy.branch_naming_patterns missing '$bp' template."
                    }
                }
            }
        }

        # Quality gates
        if (-not $configObj.quality_gates) {
            $failures += "Config missing 'quality_gates' section."
        } else {
            $cov = $configObj.quality_gates.test_coverage_threshold_percent
            if ($null -eq $cov -or ($cov -as [double]) -eq $null -or $cov -lt 0 -or $cov -gt 100) {
                $failures += "Field 'quality_gates.test_coverage_threshold_percent' must be a number between 0 and 100, got: '$cov'."
            }
            $allowedSeverities = @("Critical", "Major", "Minor", "Trivial")
            $sevs = $configObj.quality_gates.blocking_defect_severities
            if ($null -eq $sevs -or $sevs.Count -eq 0) {
                $failures += "Field 'quality_gates.blocking_defect_severities' must be a non-empty array."
            } else {
                foreach ($s in $sevs) {
                    if ($s -notin $allowedSeverities) {
                        $failures += "Invalid severity in blocking_defect_severities: '$s'. Allowed values: $($allowedSeverities -join ', ')."
                    }
                }
            }
        }

        # Paths section & containment
        if (-not $configObj.paths) {
            $failures += "Config missing 'paths' section."
        } else {
            $requiredPaths = @("vault_relative_path", "sessions_relative_path", "worktrees_relative_path")
            foreach ($rp in $requiredPaths) {
                $val = $configObj.paths.$rp
                if ([string]::IsNullOrWhiteSpace($val)) {
                    $failures += "Field 'paths.$rp' must not be empty."
                } elseif ([System.IO.Path]::IsPathRooted($val)) {
                    $failures += "Field 'paths.$rp' must be relative, got absolute: '$val'."
                } else {
                    $combined = [System.IO.Path]::Combine($canonicalProjectRoot, $val)
                    $resolved = [System.IO.Path]::GetFullPath($combined)
                    if (-not (Test-IsStrictInside $resolved $canonicalProjectRoot)) {
                        $failures += "Field 'paths.$rp' ('$val') traverses outside project root: '$resolved'."
                    }
                    if (Test-IsSameOrInside $resolved $canonicalSkillRoot) {
                        $failures += "Field 'paths.$rp' ('$val') resolves inside skill root: '$resolved'."
                    }
                }
            }
        }

        # Efficiency section (token optimizer) - optional, strictly validated when present
        if (-not ($configObj.PSObject.Properties['efficiency'] -and $configObj.efficiency)) {
            Write-Host "    [WARN] Config has no 'efficiency' section: usage audit limits and paths fall back to defaults (copy the block from assets/config-template.json)."
        } else {
            $eff = $configObj.efficiency
            $aid = $eff.audit_interval_days
            if ($null -ne $aid -and (($aid -isnot [int] -and $aid -isnot [long]) -or $aid -lt 1 -or $aid -gt 30)) {
                $failures += "Field 'efficiency.audit_interval_days' must be an integer between 1 and 30, got: '$aid'."
            }
            if ($null -ne $eff.audit_model -and [string]::IsNullOrWhiteSpace([string]$eff.audit_model)) {
                $failures += "Field 'efficiency.audit_model' must be a non-empty string."
            }
            if ($null -ne $eff.rules) {
                foreach ($rule in $eff.rules.PSObject.Properties) {
                    if ($null -eq ($rule.Value -as [double])) {
                        $failures += "Field 'efficiency.rules.$($rule.Name)' must be a number, got: '$($rule.Value)'."
                    }
                }
            }
            foreach ($rp in @("ledger_path", "jobs_log_path", "reports_path")) {
                $val = $eff.$rp
                if ($null -eq $val) { continue }
                if ([string]::IsNullOrWhiteSpace($val)) {
                    $failures += "Field 'efficiency.$rp' must not be empty."
                } elseif ([System.IO.Path]::IsPathRooted($val)) {
                    $failures += "Field 'efficiency.$rp' must be relative, got absolute: '$val'."
                } else {
                    $resolved = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($canonicalProjectRoot, $val))
                    if (-not (Test-IsStrictInside $resolved $canonicalProjectRoot)) {
                        $failures += "Field 'efficiency.$rp' ('$val') traverses outside project root: '$resolved'."
                    }
                    if (Test-IsSameOrInside $resolved $canonicalSkillRoot) {
                        $failures += "Field 'efficiency.$rp' ('$val') resolves inside skill root: '$resolved'."
                    }
                }
            }
        }

        # Content review section (Content & Localization Reviewer) - optional, strictly validated when present
        if (-not ($configObj.PSObject.Properties['content_review'] -and $configObj.content_review)) {
            Write-Host "    [WARN] Config has no 'content_review' section: content review uses defaults (source locale 'en', any locale found, standard resource globs)."
        } else {
            $crv = $configObj.content_review
            if ($null -ne $crv.enabled -and $crv.enabled -isnot [bool]) {
                $failures += "Field 'content_review.enabled' must be a boolean."
            }
            if ($null -ne $crv.source_locale -and [string]::IsNullOrWhiteSpace([string]$crv.source_locale)) {
                $failures += "Field 'content_review.source_locale' must be a non-empty string."
            }
            if ($null -ne $crv.locales) {
                if (@($crv.locales).Count -eq 0) {
                    $failures += "Field 'content_review.locales' must be a non-empty array of locale codes."
                }
                foreach ($loc in @($crv.locales)) {
                    if ([string]::IsNullOrWhiteSpace([string]$loc)) { $failures += "Field 'content_review.locales' contains an empty entry." }
                }
            }
            foreach ($cp in @($crv.checkpoints)) {
                if ($cp -notin @("task-creation", "pre-release")) {
                    $failures += "Invalid content_review.checkpoints entry: '$cp'. Allowed: task-creation, pre-release."
                }
            }
            foreach ($s in @($crv.block_release_on)) {
                if ($s -notin @("Critical", "Major", "Minor", "Trivial")) {
                    $failures += "Invalid severity in content_review.block_release_on: '$s'."
                }
            }
            foreach ($rp in @("glossary_path", "style_guide_path", "reports_path")) {
                $val = $crv.$rp
                if ($null -eq $val) { continue }
                if ([string]::IsNullOrWhiteSpace($val)) {
                    $failures += "Field 'content_review.$rp' must not be empty."
                } elseif ([System.IO.Path]::IsPathRooted($val)) {
                    $failures += "Field 'content_review.$rp' must be relative, got absolute: '$val'."
                } else {
                    $resolved = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($canonicalProjectRoot, $val))
                    if (-not (Test-IsStrictInside $resolved $canonicalProjectRoot)) {
                        $failures += "Field 'content_review.$rp' ('$val') traverses outside project root: '$resolved'."
                    }
                }
            }
            foreach ($lp in @("text_sources", "markup_sources", "content_data_sources", "exclude")) {
                $val = $crv.$lp
                if ($null -ne $val -and -not ($val -is [System.Collections.IList])) {
                    $failures += "Field 'content_review.$lp' must be an array of glob patterns."
                }
            }
            foreach ($it in @($crv.inline_tables)) {
                if ($null -eq $it) { continue }
                if ([string]::IsNullOrWhiteSpace([string]$it.path) -or $null -eq $it.locales -or @($it.locales).Count -eq 0) {
                    $failures += "Each content_review.inline_tables entry needs 'path' and a non-empty 'locales' array."
                }
            }
        }

        # Operating profile (workflows/operating-profiles.md) - optional; absent means production
        if (-not $configObj.PSObject.Properties['operating_profile']) {
            Write-Host "    [WARN] Config has no 'operating_profile': defaults to production (see workflows/operating-profiles.md)."
        } elseif ($configObj.operating_profile -isnot [string] -or $configObj.operating_profile -cnotin @("prototype", "pilot", "production")) {
            $failures += "Invalid operating_profile: '$($configObj.operating_profile)'. Allowed: prototype, pilot, production."
        }

        # Profile review facts - optional, types strictly validated when present
        if ($configObj.PSObject.Properties['profile_review']) {
            $prv = $configObj.profile_review
            if ($prv -isnot [System.Management.Automation.PSCustomObject]) {
                $failures += "Field 'profile_review' must be an object."
            } else {
                $reviewKeys = @("active_users", "payments_live", "sla_promised", "regulated_data", "reviewed_at", "note")
                foreach ($rk in $prv.PSObject.Properties) {
                    if ($rk.Name -cnotin $reviewKeys) {
                        $failures += "Unknown field 'profile_review.$($rk.Name)'. Allowed: $($reviewKeys -join ', ')."
                    }
                }
                if ($prv.PSObject.Properties['active_users']) {
                    $au = $prv.active_users
                    if (($au -isnot [int] -and $au -isnot [long]) -or $au -lt 0) {
                        $failures += "Field 'profile_review.active_users' must be an integer >= 0, got: '$au'."
                    }
                }
                foreach ($bk in @("payments_live", "sla_promised", "regulated_data")) {
                    if ($prv.PSObject.Properties[$bk] -and $prv.$bk -isnot [bool]) {
                        $failures += "Field 'profile_review.$bk' must be a boolean (true/false), got: '$($prv.$bk)'."
                    }
                }
                foreach ($sk in @("reviewed_at", "note")) {
                    # ConvertFrom-Json turns ISO timestamps into DateTime; both come from a JSON string
                    if ($prv.PSObject.Properties[$sk] -and $prv.$sk -isnot [string] -and $prv.$sk -isnot [datetime]) {
                        $failures += "Field 'profile_review.$sk' must be a string."
                    }
                }
            }
        }

        # Documents listed on the dashboard - optional array of {title, path} with paths relative to the project root
        if ($configObj.PSObject.Properties['documents']) {
            $docs = $configObj.documents
            if ($docs -isnot [System.Array]) {
                $failures += "Field 'documents' must be an array of {title, path} objects."
            } else {
                for ($i = 0; $i -lt $docs.Count; $i++) {
                    $doc = $docs[$i]
                    if ($doc -isnot [System.Management.Automation.PSCustomObject]) {
                        $failures += "Field 'documents[$i]' must be an object with 'title' and 'path'."
                        continue
                    }
                    foreach ($dk in $doc.PSObject.Properties) {
                        if ($dk.Name -cnotin @("title", "path")) {
                            $failures += "Unknown field 'documents[$i].$($dk.Name)'. Allowed: title, path."
                        }
                    }
                    if ($doc.title -isnot [string] -or [string]::IsNullOrWhiteSpace($doc.title)) {
                        $failures += "Field 'documents[$i].title' must be a non-empty string."
                    }
                    $docPath = $doc.path
                    if ($docPath -isnot [string] -or [string]::IsNullOrWhiteSpace($docPath)) {
                        $failures += "Field 'documents[$i].path' must be a non-empty string."
                    } elseif ([System.IO.Path]::IsPathRooted($docPath)) {
                        $failures += "Field 'documents[$i].path' must be relative to the project root, got absolute: '$docPath'."
                    } else {
                        $resolved = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($canonicalProjectRoot, $docPath))
                        if (-not (Test-IsStrictInside $resolved $canonicalProjectRoot)) {
                            $failures += "Field 'documents[$i].path' ('$docPath') traverses outside project root: '$resolved'."
                        }
                    }
                }
            }
        }

        if ($failures.Count -eq 0) {
            Write-Host "    [PASS] .it-department/config.json is valid and strictly conforms to contract."
        }
    } catch {
        $failures += "Failed to read or parse .it-department/config.json: $_"
    }
}

# 2. Validate Configured Directories (if config was loaded)
if ($configObj -and $configObj.paths) {
    $resolvedVaultDir = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($canonicalProjectRoot, $configObj.paths.vault_relative_path))
    $resolvedSessionsDir = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($canonicalProjectRoot, $configObj.paths.sessions_relative_path))
    $resolvedWorktreesDir = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($canonicalProjectRoot, $configObj.paths.worktrees_relative_path))

    # Validate Vault Directories & Dashboard
    $requiredVaultSubdirs = @(
        "01-Tasks/Backlog",
        "01-Tasks/In-Analysis",
        "01-Tasks/Ready-For-Dev",
        "01-Tasks/In-Development",
        "01-Tasks/Code-Review",
        "01-Tasks/QA-Testing",
        "01-Tasks/Ready-For-Release",
        "02-Bugs",
        "03-ADR",
        "04-Archive/Completed-Tasks",
        "04-Archive/Resolved-Bugs",
        "04-Archive/Deprecated-Proposals",
        "05-Reports",
        "06-Content"
    )

    foreach ($sub in $requiredVaultSubdirs) {
        $targetSub = Join-Path $resolvedVaultDir $sub
        if (-not (Test-Path -LiteralPath $targetSub)) {
            $failures += "Missing required vault directory at resolved path: $targetSub (re-run init-project to add folders introduced by newer skill versions)"
        }
    }

    $dashboardPath = Join-Path $resolvedVaultDir "00-Dashboard.md"
    if (-not (Test-Path -LiteralPath $dashboardPath)) {
        $failures += "Missing dashboard at resolved vault path: $dashboardPath"
    }

    $decisionsLogPath = Join-Path $resolvedVaultDir "03-ADR/decisions-log.md"
    if (-not (Test-Path -LiteralPath $decisionsLogPath)) {
        Write-Host "    [WARN] Missing decisions journal at resolved vault path: $decisionsLogPath (re-run init-project to add it; row format: templates/decision-record.md)."
    }

    # Validate Sessions and Worktrees directories
    if (-not (Test-Path -LiteralPath $resolvedSessionsDir)) {
        $failures += "Missing configured sessions directory: $resolvedSessionsDir"
    }
    if (-not (Test-Path -LiteralPath $resolvedWorktreesDir)) {
        $failures += "Missing configured worktrees directory: $resolvedWorktreesDir"
    }

    if ($failures.Count -eq 0) {
        Write-Host "    [PASS] Configured vault, sessions, and worktrees directories verified."
    }

    # 3. Check for Fictional Example Leakage in Configured Vault
    $leakCheckPaths = @(
        (Join-Path $resolvedVaultDir "01-Tasks/Backlog/SHOP-102.md"),
        (Join-Path $resolvedVaultDir "01-Tasks/Ready-For-Dev/SHOP-102.md")
    )
    foreach ($leak in $leakCheckPaths) {
        if (Test-Path -LiteralPath $leak) {
            $failures += "Fictional example SHOP-102 was erroneously copied into active project backlog: $leak"
        }
    }
    if ($failures.Count -eq 0) {
        Write-Host "    [PASS] Fictional example isolation confirmed."
    }
}

# 4. Check Skill Package Hygiene (No runtime files in Skill Root)
$pollutedSkillPaths = @(
    (Join-Path $canonicalSkillRoot "vault"),
    (Join-Path $canonicalSkillRoot "config.json"),
    (Join-Path $canonicalSkillRoot ".it-department")
)
foreach ($badPath in $pollutedSkillPaths) {
    if (Test-Path -LiteralPath $badPath) {
        $failures += "Skill package contains active runtime data at: $badPath (violates package separation)"
    }
}
if ($failures.Count -eq 0) {
    Write-Host "    [PASS] Skill package root hygiene confirmed."
}

# 5. Vault Lint (scripts/vault_lint.py): frontmatter, status vs folder, links, severities; errors fail validation
$lintScript = Join-Path $canonicalSkillRoot "scripts/vault_lint.py"
$vaultPathRejected = [bool]($failures -match "paths\.vault_relative_path")
if ($configObj -and $configObj.paths -and $resolvedVaultDir -and -not $vaultPathRejected -and (Test-Path -LiteralPath $resolvedVaultDir)) {
    $python = Find-Python
    if (-not (Test-Path -LiteralPath $lintScript)) {
        Write-Host "    [WARN] $lintScript not found: vault lint skipped"
    } elseif (-not $python) {
        Write-Host "    [WARN] Python not available: vault lint skipped"
    } else {
        $lintArgs = @($python | Select-Object -Skip 1) + @($lintScript, "--root", $canonicalProjectRoot, "--no-dashboard-check")
        $previousPreference = $ErrorActionPreference
        $previousIoEncoding = $env:PYTHONIOENCODING
        $previousOutputEncoding = $null
        try { $previousOutputEncoding = [Console]::OutputEncoding; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
        try {
            $ErrorActionPreference = 'Continue'
            $env:PYTHONIOENCODING = 'utf-8'
            $lintOutput = @(& $python[0] @lintArgs 2>&1 | ForEach-Object { "$_" })
            $lintExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousPreference
            $env:PYTHONIOENCODING = $previousIoEncoding
            if ($previousOutputEncoding) { try { [Console]::OutputEncoding = $previousOutputEncoding } catch { } }
        }
        Write-Host "    Vault lint ($($python -join ' ') scripts/vault_lint.py --no-dashboard-check):"
        foreach ($line in $lintOutput) { Write-Host "      $line" }
        if ($lintExit -eq 0) {
            Write-Host "    [PASS] Vault lint found no errors."
        } else {
            $failures += "Vault lint reported errors (vault_lint.py exit $lintExit); fix the findings listed above."
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Error "Validation failed with $($failures.Count) error(s):`n$($failures -join "`n")"
    exit 1
} else {
    Write-Host "==> All validation checks passed successfully!"
}
