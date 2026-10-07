<#
.SYNOPSIS
    Updates an installed copy of the IT Department skill to the latest version and migrates a project.
.DESCRIPTION
    Detects how this skill folder was installed and updates it the matching way:
      git        the folder is a git checkout            -> git fetch + checkout -Ref (default: the default branch)
      skills-cli the project's skills-lock.json lists it -> npx skills update <name> -y -p   (Agent Skills CLI)
      plugin     the folder is in a Claude plugin cache  -> claude plugin update it-departament-skill@it-departament
      copy       anything else                           -> git clone -Ref of -Repo and mirror it over the folder
    Afterwards it prints the CHANGELOG entries between the old and the new version (their "Migration" notes are
    the manual steps), and - when a project root is given or can be inferred from the folder location
    (<project>/.agents/skills/... or <project>/.claude/skills/...) - re-runs init-project (adds new folders and
    files, never overwrites) and validate-project on that project.
.PARAMETER SkillRoot   Installed skill folder. Default: the parent of this script.
.PARAMETER ProjectRoot Project to migrate after the update. Default: inferred from SkillRoot, else none.
.PARAMETER Ref         Git tag or branch to update to. Default: the repository's default branch.
.PARAMETER Repo        Git URL or local path of the upstream repository. Default: "repository" in .claude-plugin/plugin.json.
.PARAMETER Mode        Force the update mode: git | skills-cli | plugin | copy. Default: detected.
.PARAMETER Check       Only compare the installed version with upstream. Exit 0 = up to date, 1 = update available.
.PARAMETER DryRun      Print what would be done without changing anything.
.PARAMETER NoMigrate   Skip init-project / validate-project after the update.
.OUTPUTS
    Exit codes: 0 success / up to date, 1 update available (-Check) or update failed, 2 bad arguments or unsafe
    folder, 3 updated but validate-project failed (read the output).
#>
[CmdletBinding()]
param(
    [string]$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ProjectRoot = "",
    [string]$Ref = "",
    [string]$Repo = "",
    [ValidateSet("", "git", "skills-cli", "plugin", "copy")]
    [string]$Mode = "",
    [switch]$Check,
    [switch]$DryRun,
    [switch]$NoMigrate
)

$ErrorActionPreference = "Stop"
$DefaultRepo = "https://github.com/Abdukhalil-zoda/it-departament-skill"
$PluginId = "it-departament-skill@it-departament"

function Get-SkillVersion([string]$dir) {
    $f = Join-Path $dir "VERSION"
    if (Test-Path -LiteralPath $f) { return (Get-Content -Raw -LiteralPath $f).Trim() }
    return "0.0.0"
}
function ConvertTo-VersionObject([string]$v) {
    $m = [regex]::Match($v, '(\d+)\.(\d+)\.(\d+)')
    if ($m.Success) { return [version]::new([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value) }
    return $null
}
function Get-RepoUrl([string]$dir) {
    if ($Repo) { return $Repo }
    $manifest = Join-Path $dir ".claude-plugin\plugin.json"
    if (Test-Path -LiteralPath $manifest) {
        try { $j = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json; if ($j.repository) { return [string]$j.repository } } catch {}
    }
    return $DefaultRepo
}
function Get-UpstreamVersion([string]$repoUrl, [string]$ref) {
    # 1) newest v<semver> tag; 2) VERSION file on the ref (GitHub raw) or in a local repo path
    try {
        $tags = & git ls-remote --tags --refs $repoUrl 2>$null
        $best = $null
        foreach ($line in @($tags)) {
            if ($line -match 'refs/tags/v?(\d+\.\d+\.\d+)$') { $v = ConvertTo-VersionObject $Matches[1]; if ($v -and (-not $best -or $v -gt $best)) { $best = $v } }
        }
        if ($best -and -not $ref) { return $best.ToString() }
    } catch {}
    if (Test-Path -LiteralPath $repoUrl) {
        try { $r = if ($ref) { $ref } else { "HEAD" }; $txt = & git -C $repoUrl show "${r}:VERSION" 2>$null; if ($txt) { return ([string]$txt).Trim() } } catch {}
        return "unknown"
    }
    if ($repoUrl -match '^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$') {
        $r = if ($ref) { $ref } else { "HEAD" }
        $raw = "https://raw.githubusercontent.com/$($Matches[1])/$($Matches[2])/$r/VERSION"
        try { return ((Invoke-WebRequest -Uri $raw -UseBasicParsing -TimeoutSec 20).Content).Trim() } catch { return "unknown" }
    }
    return "unknown"
}
function Get-ChangelogSlice([string]$dir, [string]$fromVersion, [string]$toVersion) {
    $f = Join-Path $dir "CHANGELOG.md"
    if (-not (Test-Path -LiteralPath $f)) { return @() }
    $from = ConvertTo-VersionObject $fromVersion; $to = ConvertTo-VersionObject $toVersion
    $out = @(); $keep = $false
    foreach ($line in (Get-Content -LiteralPath $f)) {
        if ($line -match '^## \[(\d+\.\d+\.\d+)\]') {
            $v = ConvertTo-VersionObject $Matches[1]
            $keep = ($v -and ((-not $from) -or $v -gt $from) -and ((-not $to) -or $v -le $to))
        }
        if ($keep) { $out += $line }
    }
    return $out
}
function Find-ProjectRoot([string]$dir) {
    $d = [System.IO.DirectoryInfo]::new($dir)
    $parent = $d.Parent
    if ($parent -and $parent.Name -eq "skills" -and $parent.Parent -and ($parent.Parent.Name -eq ".agents" -or $parent.Parent.Name -eq ".claude") -and $parent.Parent.Parent) {
        return $parent.Parent.Parent.FullName
    }
    return ""
}
function Assert-SafeSkillFolder([string]$dir) {
    if (-not (Test-Path -LiteralPath (Join-Path $dir "SKILL.md"))) { throw "'$dir' is not a skill folder (no SKILL.md)." }
    foreach ($bad in @(".it-department", "vault")) {
        if (Test-Path -LiteralPath (Join-Path $dir $bad)) { throw "'$dir' contains project data ($bad); refusing to mirror over it." }
    }
}

# --- resolve ---------------------------------------------------------------------------------------------------------
$SkillRoot = [System.IO.Path]::GetFullPath($SkillRoot)
if (-not (Test-Path -LiteralPath $SkillRoot -PathType Container)) { Write-Error "SkillRoot not found: $SkillRoot"; exit 2 }
$name = Split-Path -Leaf $SkillRoot
$repoUrl = Get-RepoUrl $SkillRoot
if (-not $ProjectRoot) { $ProjectRoot = Find-ProjectRoot $SkillRoot }
if ($ProjectRoot) { $ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot) }
$oldVersion = Get-SkillVersion $SkillRoot

if (-not $Mode) {
    if (Test-Path -LiteralPath (Join-Path $SkillRoot ".git")) { $Mode = "git" }
    elseif ($SkillRoot -match '[\\/]\.claude[\\/]plugins[\\/]') { $Mode = "plugin" }
    elseif ($ProjectRoot -and (Test-Path -LiteralPath (Join-Path $ProjectRoot "skills-lock.json")) -and ((Get-Content -Raw -LiteralPath (Join-Path $ProjectRoot "skills-lock.json")) -match ('"' + [regex]::Escape($name) + '"'))) { $Mode = "skills-cli" }
    else { $Mode = "copy" }
}

Write-Host "==> IT Department skill updater"
Write-Host "    Skill folder: $SkillRoot ($name)"
Write-Host "    Installed:    $oldVersion   Mode: $Mode   Upstream: $repoUrl$(if ($Ref) { " @ $Ref" })"
if ($ProjectRoot) { Write-Host "    Project:      $ProjectRoot" } else { Write-Host "    Project:      (none - pass -ProjectRoot to migrate a project)" }

# --- check only ------------------------------------------------------------------------------------------------------
if ($Check) {
    $up = Get-UpstreamVersion $repoUrl $Ref
    Write-Host "    Upstream:     $up"
    $o = ConvertTo-VersionObject $oldVersion; $u = ConvertTo-VersionObject $up
    if ($u -and $o -and $u -gt $o) { Write-Host "==> Update available: $oldVersion -> $up"; exit 1 }
    if ($u -and $o -and $u -le $o) { Write-Host "==> Up to date."; exit 0 }
    Write-Host "==> Could not determine the upstream version (no tags or VERSION reachable)."; exit 0
}

# --- update ----------------------------------------------------------------------------------------------------------
switch ($Mode) {
    "git" {
        $dirty = & git -C $SkillRoot status --porcelain
        if ($dirty) { Write-Error "The checkout has uncommitted changes; commit or stash them first."; exit 1 }
        $target = if ($Ref) { $Ref } else { (& git -C $SkillRoot symbolic-ref --short refs/remotes/origin/HEAD 2>$null) -replace '^origin/', '' }
        if (-not $target) { $target = "master" }
        Write-Host "    git fetch --tags origin; git checkout $target; git pull --ff-only (branches)"
        if (-not $DryRun) {
            & git -C $SkillRoot fetch --tags --prune origin | Out-Null
            & git -C $SkillRoot checkout -q $target
            if ($LASTEXITCODE -ne 0) { Write-Error "git checkout $target failed"; exit 1 }
            & git -C $SkillRoot show-ref --verify --quiet "refs/remotes/origin/$target"
            $isBranch = ($LASTEXITCODE -eq 0)
            if ($isBranch) { & git -C $SkillRoot pull -q --ff-only origin $target; if ($LASTEXITCODE -ne 0) { Write-Error "git pull --ff-only failed"; exit 1 } }
        }
    }
    "skills-cli" {
        Write-Host "    npx -y skills update $name -y -p   (in $ProjectRoot)"
        if (-not $DryRun) {
            Push-Location -LiteralPath $ProjectRoot
            try { & npx -y skills update $name -y -p; if ($LASTEXITCODE -ne 0) { Write-Error "npx skills update failed"; exit 1 } } finally { Pop-Location }
        }
    }
    "plugin" {
        Write-Host "    claude plugin update $PluginId"
        if (-not $DryRun) {
            & claude plugin update $PluginId
            if ($LASTEXITCODE -ne 0) { Write-Error "claude plugin update failed"; exit 1 }
            Write-Host "    Run /reload-plugins in open sessions to load the new version."
        }
    }
    "copy" {
        Assert-SafeSkillFolder $SkillRoot
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("it-skill-update-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
        $cloneArgs = @("clone", "--depth", "1", "--quiet")
        if ($Ref) { $cloneArgs += @("--branch", $Ref) }
        $cloneArgs += @($repoUrl, $tmp)
        Write-Host "    git $($cloneArgs -join ' '); robocopy <clone> `"$SkillRoot`" /MIR"
        if (-not $DryRun) {
            & git @cloneArgs
            if ($LASTEXITCODE -ne 0) { Write-Error "git clone failed ($repoUrl $Ref)"; exit 1 }
            Remove-Item -LiteralPath (Join-Path $tmp ".git") -Recurse -Force
            & robocopy $tmp $SkillRoot /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
            $rc = $LASTEXITCODE
            Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
            if ($rc -ge 8) { Write-Error "robocopy failed with code $rc"; exit 1 }
        }
    }
}

if ($DryRun) { Write-Host "==> Dry run: nothing changed."; exit 0 }

$newVersion = Get-SkillVersion $SkillRoot
Write-Host "==> Skill version: $oldVersion -> $newVersion"
$slice = Get-ChangelogSlice $SkillRoot $oldVersion $newVersion
if ($slice.Count -gt 0) {
    Write-Host ""
    Write-Host "--- CHANGELOG ($oldVersion -> $newVersion); 'Migration' items are the manual steps ---"
    $slice | ForEach-Object { Write-Host $_ }
    Write-Host "--- end of changelog ---"
    Write-Host ""
} elseif ($newVersion -eq $oldVersion) {
    Write-Host "    Already at $newVersion (no changelog entries to show)."
}

# --- migrate ---------------------------------------------------------------------------------------------------------
if ($NoMigrate -or -not $ProjectRoot -or $Mode -eq "plugin") {
    if (-not $NoMigrate -and $ProjectRoot -and $Mode -eq "plugin") { Write-Host "    Plugin mode: run init-project / validate-project from the plugin folder after /reload-plugins." }
    exit 0
}
$initScript = Join-Path $SkillRoot "scripts\init-project.ps1"
$validateScript = Join-Path $SkillRoot "scripts\validate-project.ps1"
Write-Host "==> Migrating project: init-project (adds new folders and files only) + validate-project"
& pwsh -NoProfile -File $initScript -ProjectRoot $ProjectRoot -SkillRoot $SkillRoot
if ($LASTEXITCODE -ne 0) { Write-Error "init-project failed"; exit 3 }
& pwsh -NoProfile -File $validateScript -ProjectRoot $ProjectRoot -SkillRoot $SkillRoot
if ($LASTEXITCODE -ne 0) { Write-Host "==> validate-project reported problems: apply the Migration notes above, then re-run validate-project."; exit 3 }
Write-Host "==> Update complete: $name $newVersion, project validated."
exit 0
