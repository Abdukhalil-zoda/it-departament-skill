#!/usr/bin/env bash
# Comprehensive project validation script for the IT Department skill.
# Validates project configuration types, enums, path containment, and directories.
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <project-root> [skill-root]" >&2
    exit 1
fi

PROJECT_ROOT_INPUT="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT_INPUT="${2:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# Detect functional structured JSON processor
JSON_ENGINE=""
if command -v node >/dev/null 2>&1 && node -e "process.exit(0)" >/dev/null 2>&1; then
    JSON_ENGINE="node"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    JSON_ENGINE="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    JSON_ENGINE="python"
else
    echo "Error: Functional Node or Python is required to validate configuration types and enums." >&2
    exit 1
fi

resolve_canonical() {
    local target="$1"
    if [ -d "$target" ]; then
        (cd "$target" && pwd -P)
    elif [ -f "$target" ]; then
        local dir
        dir="$(cd "$(dirname "$target")" && pwd -P)"
        echo "$dir/$(basename "$target")"
    else
        local parent
        parent="$(dirname "$target")"
        local leaf
        leaf="$(basename "$target")"
        while [ ! -d "$parent" ] && [ "$parent" != "/" ] && [ "$parent" != "." ]; do
            leaf="$(basename "$parent")/$leaf"
            parent="$(dirname "$parent")"
        done
        local resolved_parent
        resolved_parent="$(cd "$parent" && pwd -P)"
        echo "$resolved_parent/$leaf"
    fi
}

SKILL_ROOT="$(resolve_canonical "$SKILL_ROOT_INPUT")"
PROJECT_ROOT="$(resolve_canonical "$PROJECT_ROOT_INPUT")"

is_same_or_inside() {
    local child="$1"
    local parent="$2"
    case "$child" in
        "$parent"|"$parent"/*) return 0 ;;
        *) return 1 ;;
    esac
}

echo "==> Validating IT Department Project Setup"
echo "    Project Root: $PROJECT_ROOT"
echo "    Skill Root:   $SKILL_ROOT"

if is_same_or_inside "$PROJECT_ROOT" "$SKILL_ROOT"; then
    echo "Error: Project root ('$PROJECT_ROOT') cannot be equal to or inside skill root ('$SKILL_ROOT')." >&2
    exit 1
fi
if is_same_or_inside "$SKILL_ROOT" "$PROJECT_ROOT"; then
    echo "Error: Skill root ('$SKILL_ROOT') cannot be inside project root ('$PROJECT_ROOT')." >&2
    exit 1
fi

PROJECT_CONFIG="$PROJECT_ROOT/.it-department/config.json"
if [ ! -f "$PROJECT_CONFIG" ]; then
    echo "Error: Missing configuration file: $PROJECT_CONFIG" >&2
    exit 1
fi

# Execute strict schema and path containment validator
if [ "$JSON_ENGINE" = "node" ]; then
    node -e '
const fs = require("fs");
const path = require("path");

const configPath = process.argv[1];
const projectRoot = path.resolve(process.argv[2]);
const skillRoot = path.resolve(process.argv[3]);

let cfg;
try {
    cfg = JSON.parse(fs.readFileSync(configPath, "utf8"));
} catch (e) {
    console.error("Failed to parse config.json: " + e.message);
    process.exit(1);
}

const errors = [];

if (cfg.schema_version !== "2.0.0") errors.push("Invalid schema_version: " + cfg.schema_version + ". Expected 2.0.0");
if (!cfg.project_name || typeof cfg.project_name !== "string") errors.push("Missing or invalid project_name.");
if (cfg.cto_mode !== "VIRTUAL" && cfg.cto_mode !== "USER") errors.push("Invalid cto_mode: " + cfg.cto_mode + ". Allowed: VIRTUAL, USER.");

const auth = cfg.delegated_authorities;
if (!auth || typeof auth !== "object") {
    errors.push("Missing delegated_authorities object.");
} else {
    const authKeys = [
        "allow_merge_integration", "allow_merge_production", "allow_deploy_production",
        "allow_infra_provisioning", "allow_destructive_operations", "allow_schema_migrations",
        "allow_dependency_updates"
    ];
    for (const k of authKeys) {
        if (typeof auth[k] !== "boolean") {
            errors.push("delegated_authorities." + k + " must be boolean, got: " + typeof auth[k]);
        }
    }
}

const gp = cfg.git_policy;
if (!gp || typeof gp !== "object") {
    errors.push("Missing git_policy object.");
} else {
    if (!gp.production_branch) errors.push("Missing git_policy.production_branch");
    if (!gp.integration_branch) errors.push("Missing git_policy.integration_branch");
    if (!gp.branch_naming_patterns || !gp.branch_naming_patterns.feature || !gp.branch_naming_patterns.bug || !gp.branch_naming_patterns.hotfix) {
        errors.push("Missing git_policy.branch_naming_patterns (feature, bug, hotfix)");
    }
}

const qg = cfg.quality_gates;
if (!qg || typeof qg !== "object") {
    errors.push("Missing quality_gates object.");
} else {
    const cov = qg.test_coverage_threshold_percent;
    if (typeof cov !== "number" || cov < 0 || cov > 100) {
        errors.push("Invalid test_coverage_threshold_percent: " + cov + ". Must be 0-100.");
    }
    const sevs = qg.blocking_defect_severities;
    if (!Array.isArray(sevs) || sevs.length === 0) {
        errors.push("blocking_defect_severities must be non-empty array");
    } else {
        const allowed = new Set(["Critical", "Major", "Minor", "Trivial"]);
        for (const s of sevs) {
            if (!allowed.has(s)) errors.push("Invalid severity in blocking_defect_severities: " + s);
        }
    }
}

const p = cfg.paths;
if (!p || typeof p !== "object") {
    errors.push("Missing paths object.");
} else {
    for (const k of ["vault_relative_path", "sessions_relative_path", "worktrees_relative_path"]) {
        const val = p[k];
        if (!val || typeof val !== "string") {
            errors.push("paths." + k + " must be non-empty string");
        } else if (path.isAbsolute(val)) {
            errors.push("paths." + k + " must be relative, got: " + val);
        } else {
            const resolved = path.resolve(projectRoot, val);
            const rel = path.relative(projectRoot, resolved);
            if (rel.startsWith("..") || rel === "") {
                errors.push("paths." + k + " (" + val + ") resolves outside project_root: " + resolved);
            }
            const relSkill = path.relative(skillRoot, resolved);
            if (!relSkill.startsWith("..")) {
                errors.push("paths." + k + " (" + val + ") resolves inside skill_root: " + resolved);
            }
        }
    }
}

// Efficiency section (token optimizer) - optional, strictly validated when present
const eff = cfg.efficiency;
if (eff === undefined || eff === null) {
    console.log("    [WARN] Config has no efficiency section: usage audit limits and paths fall back to defaults (copy the block from assets/config-template.json).");
} else if (typeof eff !== "object" || Array.isArray(eff)) {
    errors.push("efficiency must be an object.");
} else {
    const aid = eff.audit_interval_days;
    if (aid !== undefined && (!Number.isInteger(aid) || aid < 1 || aid > 30)) {
        errors.push("efficiency.audit_interval_days must be an integer between 1 and 30, got: " + aid);
    }
    if (eff.audit_model !== undefined && (typeof eff.audit_model !== "string" || !eff.audit_model.trim())) {
        errors.push("efficiency.audit_model must be a non-empty string.");
    }
    if (eff.rules !== undefined) {
        if (typeof eff.rules !== "object" || Array.isArray(eff.rules) || eff.rules === null) {
            errors.push("efficiency.rules must be an object.");
        } else {
            for (const [rk, rv] of Object.entries(eff.rules)) {
                if (typeof rv !== "number" || Number.isNaN(rv)) errors.push("efficiency.rules." + rk + " must be a number, got: " + typeof rv);
            }
        }
    }
    for (const k of ["ledger_path", "jobs_log_path", "reports_path"]) {
        const val = eff[k];
        if (val === undefined) continue;
        if (!val || typeof val !== "string") {
            errors.push("efficiency." + k + " must be a non-empty string");
        } else if (path.isAbsolute(val)) {
            errors.push("efficiency." + k + " must be relative, got: " + val);
        } else {
            const resolved = path.resolve(projectRoot, val);
            const rel = path.relative(projectRoot, resolved);
            if (rel.startsWith("..") || rel === "") {
                errors.push("efficiency." + k + " (" + val + ") resolves outside project_root: " + resolved);
            }
            const relSkill = path.relative(skillRoot, resolved);
            if (!relSkill.startsWith("..")) {
                errors.push("efficiency." + k + " (" + val + ") resolves inside skill_root: " + resolved);
            }
        }
    }
}

// Content review section (Content & Localization Reviewer) - optional, strictly validated when present
const crv = cfg.content_review;
if (crv === undefined || crv === null) {
    console.log("    [WARN] Config has no content_review section: content review uses defaults (source locale en, any locale found, standard resource globs).");
} else if (typeof crv !== "object" || Array.isArray(crv)) {
    errors.push("content_review must be an object.");
} else {
    if (crv.enabled !== undefined && typeof crv.enabled !== "boolean") errors.push("content_review.enabled must be a boolean.");
    if (crv.source_locale !== undefined && (typeof crv.source_locale !== "string" || !crv.source_locale.trim())) errors.push("content_review.source_locale must be a non-empty string.");
    if (crv.locales !== undefined && (!Array.isArray(crv.locales) || crv.locales.length === 0 || crv.locales.some(l => typeof l !== "string" || !l.trim()))) {
        errors.push("content_review.locales must be a non-empty array of locale codes.");
    }
    if (crv.checkpoints !== undefined) {
        if (!Array.isArray(crv.checkpoints)) errors.push("content_review.checkpoints must be an array.");
        else for (const cp of crv.checkpoints) { if (cp !== "task-creation" && cp !== "pre-release") errors.push("Invalid content_review.checkpoints entry: " + cp); }
    }
    if (crv.block_release_on !== undefined) {
        const allowedSev = new Set(["Critical", "Major", "Minor", "Trivial"]);
        if (!Array.isArray(crv.block_release_on)) errors.push("content_review.block_release_on must be an array.");
        else for (const s of crv.block_release_on) { if (!allowedSev.has(s)) errors.push("Invalid severity in content_review.block_release_on: " + s); }
    }
    for (const k of ["glossary_path", "style_guide_path", "reports_path"]) {
        const val = crv[k];
        if (val === undefined) continue;
        if (!val || typeof val !== "string") { errors.push("content_review." + k + " must be a non-empty string"); continue; }
        if (path.isAbsolute(val)) { errors.push("content_review." + k + " must be relative, got: " + val); continue; }
        const rel = path.relative(projectRoot, path.resolve(projectRoot, val));
        if (rel.startsWith("..") || rel === "") errors.push("content_review." + k + " (" + val + ") resolves outside project_root");
    }
    for (const k of ["text_sources", "markup_sources", "content_data_sources", "exclude"]) {
        if (crv[k] !== undefined && !Array.isArray(crv[k])) errors.push("content_review." + k + " must be an array of glob patterns.");
    }
    if (crv.inline_tables !== undefined) {
        if (!Array.isArray(crv.inline_tables)) errors.push("content_review.inline_tables must be an array.");
        else for (const it of crv.inline_tables) {
            if (!it || typeof it.path !== "string" || !it.path || !Array.isArray(it.locales) || it.locales.length === 0) errors.push("Each content_review.inline_tables entry needs path and a non-empty locales array.");
        }
    }
}

if (errors.length > 0) {
    console.error(errors.join("\n"));
    process.exit(1);
}
' "$PROJECT_CONFIG" "$PROJECT_ROOT" "$SKILL_ROOT"
else
    $JSON_ENGINE -c '
import json, sys, os

config_path = sys.argv[1]
project_root = os.path.realpath(sys.argv[2])
skill_root = os.path.realpath(sys.argv[3])

with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

errors = []

schema_version = cfg.get("schema_version")
if schema_version != "2.0.0":
    errors.append(f"Invalid schema_version: {schema_version}. Expected 2.0.0")

if not cfg.get("project_name") or not isinstance(cfg.get("project_name"), str):
    errors.append("Missing or invalid project_name.")

cto_mode = cfg.get("cto_mode")
if cto_mode not in ["VIRTUAL", "USER"]:
    errors.append(f"Invalid cto_mode: {cto_mode}. Allowed: VIRTUAL, USER.")

auth = cfg.get("delegated_authorities")
if not isinstance(auth, dict):
    errors.append("Missing delegated_authorities object.")
else:
    auth_keys = [
        "allow_merge_integration", "allow_merge_production", "allow_deploy_production",
        "allow_infra_provisioning", "allow_destructive_operations", "allow_schema_migrations",
        "allow_dependency_updates"
    ]
    for k in auth_keys:
        val = auth.get(k)
        if not isinstance(val, bool):
            errors.append(f"delegated_authorities.{k} must be boolean, got: {type(val).__name__} ({val})")

git_pol = cfg.get("git_policy")
if not isinstance(git_pol, dict):
    errors.append("Missing git_policy object.")
else:
    if not git_pol.get("production_branch"): errors.append("Missing git_policy.production_branch")
    if not git_pol.get("integration_branch"): errors.append("Missing git_policy.integration_branch")
    bnp = git_pol.get("branch_naming_patterns")
    if not isinstance(bnp, dict):
        errors.append("Missing git_policy.branch_naming_patterns")
    else:
        for bp in ["feature", "bug", "hotfix"]:
            if not bnp.get(bp): errors.append(f"Missing branch_naming_patterns.{bp}")

qg = cfg.get("quality_gates")
if not isinstance(qg, dict):
    errors.append("Missing quality_gates object.")
else:
    cov = qg.get("test_coverage_threshold_percent")
    if not isinstance(cov, (int, float)) or cov < 0 or cov > 100:
        errors.append(f"Invalid test_coverage_threshold_percent: {cov}. Must be 0-100.")
    sevs = qg.get("blocking_defect_severities")
    if not isinstance(sevs, list) or len(sevs) == 0:
        errors.append("blocking_defect_severities must be a non-empty list.")
    else:
        allowed = {"Critical", "Major", "Minor", "Trivial"}
        for s in sevs:
            if s not in allowed:
                errors.append(f"Invalid severity in blocking_defect_severities: {s}")

paths = cfg.get("paths")
if not isinstance(paths, dict):
    errors.append("Missing paths object.")
else:
    for pkey in ["vault_relative_path", "sessions_relative_path", "worktrees_relative_path"]:
        pval = paths.get(pkey)
        if not pval or not isinstance(pval, str):
            errors.append(f"paths.{pkey} must be a non-empty string.")
        elif os.path.isabs(pval):
            errors.append(f"paths.{pkey} must be relative, got: {pval}")
        else:
            resolved = os.path.realpath(os.path.join(project_root, pval))
            rel = os.path.relpath(resolved, project_root)
            if rel.startswith("..") or rel == ".":
                errors.append(f"paths.{pkey} ({pval}) resolves outside project_root: {resolved}")
            rel_skill = os.path.relpath(resolved, skill_root)
            if not rel_skill.startswith(".."):
                errors.append(f"paths.{pkey} ({pval}) resolves inside skill_root: {resolved}")

# Efficiency section (token optimizer) - optional, strictly validated when present
eff = cfg.get("efficiency")
if eff is None:
    print("    [WARN] Config has no efficiency section: usage audit limits and paths fall back to defaults (copy the block from assets/config-template.json).")
elif not isinstance(eff, dict):
    errors.append("efficiency must be an object.")
else:
    aid = eff.get("audit_interval_days")
    if aid is not None and (not isinstance(aid, int) or isinstance(aid, bool) or aid < 1 or aid > 30):
        errors.append(f"efficiency.audit_interval_days must be an integer between 1 and 30, got: {aid}")
    if "audit_model" in eff and (not isinstance(eff.get("audit_model"), str) or not eff.get("audit_model").strip()):
        errors.append("efficiency.audit_model must be a non-empty string.")
    if "rules" in eff:
        if not isinstance(eff.get("rules"), dict):
            errors.append("efficiency.rules must be an object.")
        else:
            for rk, rv in eff["rules"].items():
                if isinstance(rv, bool) or not isinstance(rv, (int, float)):
                    errors.append(f"efficiency.rules.{rk} must be a number, got: {type(rv).__name__}")
    for pkey in ["ledger_path", "jobs_log_path", "reports_path"]:
        if pkey not in eff:
            continue
        pval = eff.get(pkey)
        if not pval or not isinstance(pval, str):
            errors.append(f"efficiency.{pkey} must be a non-empty string.")
        elif os.path.isabs(pval):
            errors.append(f"efficiency.{pkey} must be relative, got: {pval}")
        else:
            resolved = os.path.realpath(os.path.join(project_root, pval))
            rel = os.path.relpath(resolved, project_root)
            if rel.startswith("..") or rel == ".":
                errors.append(f"efficiency.{pkey} ({pval}) resolves outside project_root: {resolved}")
            rel_skill = os.path.relpath(resolved, skill_root)
            if not rel_skill.startswith(".."):
                errors.append(f"efficiency.{pkey} ({pval}) resolves inside skill_root: {resolved}")

# Content review section (Content & Localization Reviewer) - optional, strictly validated when present
crv = cfg.get("content_review")
if crv is None:
    print("    [WARN] Config has no content_review section: content review uses defaults (source locale en, any locale found, standard resource globs).")
elif not isinstance(crv, dict):
    errors.append("content_review must be an object.")
else:
    if "enabled" in crv and not isinstance(crv.get("enabled"), bool):
        errors.append("content_review.enabled must be a boolean.")
    if "source_locale" in crv and (not isinstance(crv.get("source_locale"), str) or not crv.get("source_locale").strip()):
        errors.append("content_review.source_locale must be a non-empty string.")
    if "locales" in crv:
        locs = crv.get("locales")
        if not isinstance(locs, list) or not locs or any((not isinstance(l, str)) or (not l.strip()) for l in locs):
            errors.append("content_review.locales must be a non-empty array of locale codes.")
    if "checkpoints" in crv:
        cps = crv.get("checkpoints")
        if not isinstance(cps, list):
            errors.append("content_review.checkpoints must be an array.")
        else:
            for cp in cps:
                if cp not in ("task-creation", "pre-release"):
                    errors.append("Invalid content_review.checkpoints entry: " + str(cp))
    if "block_release_on" in crv:
        bro = crv.get("block_release_on")
        if not isinstance(bro, list):
            errors.append("content_review.block_release_on must be an array.")
        else:
            for s in bro:
                if s not in ("Critical", "Major", "Minor", "Trivial"):
                    errors.append("Invalid severity in content_review.block_release_on: " + str(s))
    for pkey in ["glossary_path", "style_guide_path", "reports_path"]:
        if pkey not in crv:
            continue
        pval = crv.get(pkey)
        if not pval or not isinstance(pval, str):
            errors.append("content_review." + pkey + " must be a non-empty string.")
        elif os.path.isabs(pval):
            errors.append("content_review." + pkey + " must be relative, got: " + pval)
        else:
            rel = os.path.relpath(os.path.realpath(os.path.join(project_root, pval)), project_root)
            if rel.startswith("..") or rel == ".":
                errors.append("content_review." + pkey + " (" + pval + ") resolves outside project_root")
    for lkey in ["text_sources", "markup_sources", "content_data_sources", "exclude"]:
        if lkey in crv and not isinstance(crv.get(lkey), list):
            errors.append("content_review." + lkey + " must be an array of glob patterns.")
    if "inline_tables" in crv:
        its = crv.get("inline_tables")
        if not isinstance(its, list):
            errors.append("content_review.inline_tables must be an array.")
        else:
            for it in its:
                if not isinstance(it, dict) or not isinstance(it.get("path"), str) or not it.get("path") or not isinstance(it.get("locales"), list) or not it.get("locales"):
                    errors.append("Each content_review.inline_tables entry needs path and a non-empty locales array.")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
' "$PROJECT_CONFIG" "$PROJECT_ROOT" "$SKILL_ROOT"
fi

echo "    [PASS] .it-department/config.json strictly conforms to contract."

# Read configured relative paths
if [ "$JSON_ENGINE" = "node" ]; then
    CONFIG_PATHS=$(node -e '
const fs = require("fs");
const cfg = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const p = cfg.paths || {};
console.log(p.vault_relative_path || "vault");
console.log(p.sessions_relative_path || ".it-department/sessions");
console.log(p.worktrees_relative_path || ".it-department/worktrees");
' "$PROJECT_CONFIG")
else
    CONFIG_PATHS=$($JSON_ENGINE -c '
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    cfg = json.load(f)
p = cfg.get("paths", {})
print(p.get("vault_relative_path", "vault"))
print(p.get("sessions_relative_path", ".it-department/sessions"))
print(p.get("worktrees_relative_path", ".it-department/worktrees"))
' "$PROJECT_CONFIG")
fi

IFS=$'\n' read -r -d '' VAULT_REL SESSIONS_REL WORKTREES_REL <<< "$CONFIG_PATHS" || true

RESOLVED_VAULT="$PROJECT_ROOT/$VAULT_REL"
RESOLVED_SESSIONS="$PROJECT_ROOT/$SESSIONS_REL"
RESOLVED_WORKTREES="$PROJECT_ROOT/$WORKTREES_REL"

# Verify directories
for subdir in \
    "01-Tasks/Backlog" "01-Tasks/In-Analysis" "01-Tasks/Ready-For-Dev" \
    "01-Tasks/In-Development" "01-Tasks/Code-Review" "01-Tasks/QA-Testing" \
    "01-Tasks/Ready-For-Release" "02-Bugs" "03-ADR" \
    "04-Archive/Completed-Tasks" "04-Archive/Resolved-Bugs" "04-Archive/Deprecated-Proposals" "05-Reports" "06-Content"; do
    if [ ! -d "$RESOLVED_VAULT/$subdir" ]; then
        echo "Error: Missing vault subdirectory: $RESOLVED_VAULT/$subdir (re-run init-project to add folders introduced by newer skill versions)" >&2
        exit 1
    fi
done

if [ ! -f "$RESOLVED_VAULT/00-Dashboard.md" ]; then
    echo "Error: Missing dashboard: $RESOLVED_VAULT/00-Dashboard.md" >&2
    exit 1
fi
if [ ! -d "$RESOLVED_SESSIONS" ]; then
    echo "Error: Missing sessions directory: $RESOLVED_SESSIONS" >&2
    exit 1
fi
if [ ! -d "$RESOLVED_WORKTREES" ]; then
    echo "Error: Missing worktrees directory: $RESOLVED_WORKTREES" >&2
    exit 1
fi

echo "    [PASS] Configured vault, sessions, and worktree directories verified."

# Check for fictional example leakage in configured vault
if [ -f "$RESOLVED_VAULT/01-Tasks/Backlog/SHOP-102.md" ] || [ -f "$RESOLVED_VAULT/01-Tasks/Ready-For-Dev/SHOP-102.md" ]; then
    echo "Error: Fictional example SHOP-102 was copied into active project backlog." >&2
    exit 1
fi
echo "    [PASS] Fictional example isolation confirmed."

# Check skill package hygiene
if [ -d "$SKILL_ROOT/vault" ] || [ -f "$SKILL_ROOT/config.json" ] || [ -d "$SKILL_ROOT/.it-department" ]; then
    echo "Error: Skill package contains active runtime data in root." >&2
    exit 1
fi
echo "    [PASS] Skill package root hygiene confirmed."

echo "==> All validation checks passed successfully!"
