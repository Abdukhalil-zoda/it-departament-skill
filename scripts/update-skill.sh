#!/usr/bin/env bash
# Updates an installed copy of the IT Department skill to the latest version and migrates a project.
#
#   update-skill.sh [--skill-root DIR] [--project DIR] [--ref TAG|BRANCH] [--repo URL|PATH]
#                   [--mode git|skills-cli|plugin|copy] [--check] [--dry-run] [--no-migrate]
#   update-skill.sh <project-root>      (positional shorthand for --project)
#
# Modes (detected from the skill folder unless --mode is given):
#   git         the folder is a git checkout            -> git fetch + checkout --ref (default: default branch)
#   skills-cli  the project's skills-lock.json lists it -> npx skills update <name> -y -p   (Agent Skills CLI)
#   plugin      the folder is in a Claude plugin cache  -> claude plugin update it-departament-skill@it-departament
#   copy        anything else                           -> git clone --ref of --repo and mirror it over the folder
# Afterwards: prints the CHANGELOG entries between the old and the new version ("Migration" notes are the manual
# steps) and, when a project root is given or inferred (<project>/.agents/skills/... or .claude/skills/...),
# re-runs init-project (adds new folders and files only) and validate-project on it.
# Exit codes: 0 success / up to date, 1 update available (--check) or update failed, 2 bad arguments or unsafe
# folder, 3 updated but validate-project failed.
set -euo pipefail

DEFAULT_REPO="https://github.com/Abdukhalil-zoda/it-departament-skill"
PLUGIN_ID="it-departament-skill@it-departament"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT=""; REF=""; REPO=""; MODE=""; CHECK=0; DRY=0; NO_MIGRATE=0

usage() { sed -n '2,19p' "$0" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --skill-root) SKILL_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
        --project) PROJECT_ROOT="$2"; shift 2 ;;
        --ref) REF="$2"; shift 2 ;;
        --repo) REPO="$2"; shift 2 ;;
        --mode) MODE="$2"; shift 2 ;;
        --check) CHECK=1; shift ;;
        --dry-run) DRY=1; shift ;;
        --no-migrate) NO_MIGRATE=1; shift ;;
        -h|--help) usage ;;
        -*) echo "Unknown option: $1" >&2; usage ;;
        *) PROJECT_ROOT="$1"; shift ;;
    esac
done
case "$MODE" in ""|git|skills-cli|plugin|copy) ;; *) echo "Error: --mode must be git, skills-cli, plugin or copy" >&2; exit 2 ;; esac

skill_version() { if [ -f "$1/VERSION" ]; then tr -d '[:space:]' < "$1/VERSION"; else echo "0.0.0"; fi; }
semver_of() { echo "$1" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1; }
version_gt() { [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]; }
repo_url() {
    if [ -n "$REPO" ]; then echo "$REPO"; return; fi
    local m="$SKILL_ROOT/.claude-plugin/plugin.json"
    if [ -f "$m" ]; then local r; r="$(grep -oE '"repository"[[:space:]]*:[[:space:]]*"[^"]+"' "$m" | sed -E 's/.*:[[:space:]]*"([^"]+)"/\1/')"; if [ -n "$r" ]; then echo "$r"; return; fi; fi
    echo "$DEFAULT_REPO"
}
upstream_version() {
    local url="$1" ref="$2" best="" v
    if [ -z "$ref" ]; then
        while read -r v; do v="$(semver_of "$v")"; [ -n "$v" ] || continue; if [ -z "$best" ] || version_gt "$v" "$best"; then best="$v"; fi
        done < <(git ls-remote --tags --refs "$url" 2>/dev/null | grep -oE 'refs/tags/v?[0-9]+\.[0-9]+\.[0-9]+$' || true)
        if [ -n "$best" ]; then echo "$best"; return; fi
    fi
    if [ -d "$url" ]; then git -C "$url" show "${ref:-HEAD}:VERSION" 2>/dev/null | tr -d '[:space:]' || echo "unknown"; return; fi
    if echo "$url" | grep -qE '^https://github\.com/[^/]+/[^/]+'; then
        local slug; slug="$(echo "$url" | sed -E 's#^https://github\.com/([^/]+)/([^/]+?)(\.git)?/?$#\1/\2#')"
        if command -v curl >/dev/null 2>&1; then curl -fsSL --max-time 20 "https://raw.githubusercontent.com/$slug/${ref:-HEAD}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "unknown"; return; fi
    fi
    echo "unknown"
}
changelog_slice() {
    local f="$1/CHANGELOG.md" from="$2" to="$3"
    [ -f "$f" ] || return 0
    awk -v from="$from" -v to="$to" '
        function gt(a, b,   x, y, i, n) { n = split(a, x, "."); split(b, y, "."); for (i = 1; i <= 3; i++) { if (x[i]+0 > y[i]+0) return 1; if (x[i]+0 < y[i]+0) return 0 } return 0 }
        /^## \[[0-9]+\.[0-9]+\.[0-9]+\]/ { v = $0; sub(/^## \[/, "", v); sub(/\].*/, "", v); keep = (gt(v, from) && !gt(v, to)) }
        keep { print }' "$f"
}
find_project_root() {
    local parent grand great
    parent="$(dirname "$1")"; grand="$(dirname "$parent")"; great="$(dirname "$grand")"
    if [ "$(basename "$parent")" = "skills" ] && { [ "$(basename "$grand")" = ".agents" ] || [ "$(basename "$grand")" = ".claude" ]; }; then echo "$great"; fi
}
assert_safe_skill_folder() {
    [ -f "$1/SKILL.md" ] || { echo "Error: '$1' is not a skill folder (no SKILL.md)." >&2; exit 2; }
    for bad in .it-department vault; do [ -e "$1/$bad" ] && { echo "Error: '$1' contains project data ($bad); refusing to mirror over it." >&2; exit 2; }; done
    return 0
}

# --- resolve ------------------------------------------------------------------------------------------------
[ -d "$SKILL_ROOT" ] || { echo "Error: skill folder not found: $SKILL_ROOT" >&2; exit 2; }
NAME="$(basename "$SKILL_ROOT")"
REPO_URL="$(repo_url)"
[ -n "$PROJECT_ROOT" ] || PROJECT_ROOT="$(find_project_root "$SKILL_ROOT")"
if [ -n "$PROJECT_ROOT" ]; then [ -d "$PROJECT_ROOT" ] || { echo "Error: project root not found: $PROJECT_ROOT" >&2; exit 2; }; PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"; fi
OLD="$(skill_version "$SKILL_ROOT")"
if [ -z "$MODE" ]; then
    if [ -d "$SKILL_ROOT/.git" ]; then MODE="git"
    elif echo "$SKILL_ROOT" | grep -qE '/\.claude/plugins/'; then MODE="plugin"
    elif [ -n "$PROJECT_ROOT" ] && [ -f "$PROJECT_ROOT/skills-lock.json" ] && grep -q "\"$NAME\"" "$PROJECT_ROOT/skills-lock.json"; then MODE="skills-cli"
    else MODE="copy"; fi
fi
echo "==> IT Department skill updater"
echo "    Skill folder: $SKILL_ROOT ($NAME)"
echo "    Installed:    $OLD   Mode: $MODE   Upstream: $REPO_URL${REF:+ @ $REF}"
if [ -n "$PROJECT_ROOT" ]; then echo "    Project:      $PROJECT_ROOT"; else echo "    Project:      (none - pass --project to migrate a project)"; fi

# --- check only ---------------------------------------------------------------------------------------------
if [ "$CHECK" = 1 ]; then
    UP="$(upstream_version "$REPO_URL" "$REF")"; echo "    Upstream:     $UP"
    if [ -n "$(semver_of "$UP")" ]; then
        if version_gt "$(semver_of "$UP")" "$(semver_of "$OLD")"; then echo "==> Update available: $OLD -> $UP"; exit 1; else echo "==> Up to date."; exit 0; fi
    fi
    echo "==> Could not determine the upstream version (no tags or VERSION reachable)."; exit 0
fi

# --- update -------------------------------------------------------------------------------------------------
case "$MODE" in
    git)
        if [ -n "$(git -C "$SKILL_ROOT" status --porcelain)" ]; then echo "Error: the checkout has uncommitted changes; commit or stash them first." >&2; exit 1; fi
        TARGET="$REF"
        [ -n "$TARGET" ] || TARGET="$(git -C "$SKILL_ROOT" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
        [ -n "$TARGET" ] || TARGET="master"
        echo "    git fetch --tags origin; git checkout $TARGET; git pull --ff-only (branches)"
        if [ "$DRY" = 0 ]; then
            git -C "$SKILL_ROOT" fetch --tags --prune origin >/dev/null
            git -C "$SKILL_ROOT" checkout -q "$TARGET"
            if git -C "$SKILL_ROOT" show-ref --verify --quiet "refs/remotes/origin/$TARGET"; then git -C "$SKILL_ROOT" pull -q --ff-only origin "$TARGET"; fi
        fi ;;
    skills-cli)
        echo "    npx -y skills update $NAME -y -p   (in $PROJECT_ROOT)"
        if [ "$DRY" = 0 ]; then (cd "$PROJECT_ROOT" && npx -y skills update "$NAME" -y -p); fi ;;
    plugin)
        echo "    claude plugin update $PLUGIN_ID"
        if [ "$DRY" = 0 ]; then claude plugin update "$PLUGIN_ID"; echo "    Run /reload-plugins in open sessions to load the new version."; fi ;;
    copy)
        assert_safe_skill_folder "$SKILL_ROOT"
        TMP="$(mktemp -d "${TMPDIR:-/tmp}/it-skill-update-XXXXXX")"
        echo "    git clone --depth 1 ${REF:+--branch $REF }$REPO_URL <tmp>; mirror <tmp> -> $SKILL_ROOT"
        if [ "$DRY" = 0 ]; then
            if [ -n "$REF" ]; then git clone --depth 1 --quiet --branch "$REF" "$REPO_URL" "$TMP/src"; else git clone --depth 1 --quiet "$REPO_URL" "$TMP/src"; fi
            rm -rf "$TMP/src/.git"
            if command -v rsync >/dev/null 2>&1; then
                rsync -a --delete "$TMP/src/" "$SKILL_ROOT/"
            else
                find "$SKILL_ROOT" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
                cp -R "$TMP/src/." "$SKILL_ROOT/"
            fi
            rm -rf "$TMP"
        fi ;;
esac
if [ "$DRY" = 1 ]; then echo "==> Dry run: nothing changed."; exit 0; fi

NEW="$(skill_version "$SKILL_ROOT")"
echo "==> Skill version: $OLD -> $NEW"
SLICE="$(changelog_slice "$SKILL_ROOT" "$(semver_of "$OLD")" "$(semver_of "$NEW")")"
if [ -n "$SLICE" ]; then
    echo; echo "--- CHANGELOG ($OLD -> $NEW); 'Migration' items are the manual steps ---"; echo "$SLICE"; echo "--- end of changelog ---"; echo
elif [ "$NEW" = "$OLD" ]; then echo "    Already at $NEW (no changelog entries to show)."; fi

# --- migrate ------------------------------------------------------------------------------------------------
if [ "$NO_MIGRATE" = 1 ] || [ -z "$PROJECT_ROOT" ]; then exit 0; fi
if [ "$MODE" = "plugin" ]; then echo "    Plugin mode: run init-project / validate-project from the plugin folder after /reload-plugins."; exit 0; fi
echo "==> Migrating project: init-project (adds new folders and files only) + validate-project"
bash "$SKILL_ROOT/scripts/init-project.sh" "$PROJECT_ROOT" "$SKILL_ROOT" || { echo "Error: init-project failed" >&2; exit 3; }
if ! bash "$SKILL_ROOT/scripts/validate-project.sh" "$PROJECT_ROOT" "$SKILL_ROOT"; then
    echo "==> validate-project reported problems: apply the Migration notes above, then re-run validate-project."; exit 3
fi
echo "==> Update complete: $NAME $NEW, project validated."
