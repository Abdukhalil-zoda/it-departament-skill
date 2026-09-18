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

$canonicalSkillRoot = Get-CanonicalPath $SkillRoot
$canonicalProjectRoot = Get-CanonicalPath $ProjectRoot

Write-Host "==> Validating IT Department Project Setup"
Write-Host "    Project Root: $canonicalProjectRoot"
Write-Host "    Skill Root:   $canonicalSkillRoot"

# Boundary check: ProjectRoot must not be equal to or inside SkillRoot
if (Test-IsSameOrInside $canonicalProjectRoot $canonicalSkillRoot) {
    $failures += "Project root ('$canonicalProjectRoot') cannot be equal to or inside skill root ('$canonicalSkillRoot')."
}
if (Test-IsSameOrInside $canonicalSkillRoot $canonicalProjectRoot) {
    $failures += "Skill root ('$canonicalSkillRoot') cannot be inside project root ('$canonicalProjectRoot')."
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
        "04-Archive/Deprecated-Proposals"
    )

    foreach ($sub in $requiredVaultSubdirs) {
        $targetSub = Join-Path $resolvedVaultDir $sub
        if (-not (Test-Path -LiteralPath $targetSub)) {
            $failures += "Missing required vault directory at resolved path: $targetSub"
        }
    }

    $dashboardPath = Join-Path $resolvedVaultDir "00-Dashboard.md"
    if (-not (Test-Path -LiteralPath $dashboardPath)) {
        $failures += "Missing dashboard at resolved vault path: $dashboardPath"
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

if ($failures.Count -gt 0) {
    Write-Error "Validation failed with $($failures.Count) error(s):`n$($failures -join "`n")"
    exit 1
} else {
    Write-Host "==> All validation checks passed successfully!"
}
