#!/usr/bin/env bash
# Idempotent project initialization script for the IT Department skill.
# Enforces strict pre-mutation path validation and structured JSON serialization.
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <project-root> [skill-root] [project-name]" >&2
    exit 1
fi

PROJECT_ROOT_INPUT="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT_INPUT="${2:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_NAME_INPUT="${3:-$(basename "$PROJECT_ROOT_INPUT")}"

# Detect structured JSON processor with functional execution check
JSON_ENGINE=""
if command -v node >/dev/null 2>&1 && node -e "process.exit(0)" >/dev/null 2>&1; then
    JSON_ENGINE="node"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    JSON_ENGINE="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    JSON_ENGINE="python"
elif command -v jq >/dev/null 2>&1; then
    JSON_ENGINE="jq"
else
    echo "Error: No functional JSON processor (node, python3, or jq) is available." >&2
    echo "Structured JSON generation is required to prevent syntax corruption." >&2
    exit 1
fi

# Canonical path resolution helper
resolve_canonical() {
    local target="$1"
    if [ -d "$target" ]; then
        (cd "$target" && pwd -P)
    elif [ -f "$target" ]; then
        local dir
        dir="$(cd "$(dirname "$target")" && pwd -P)"
        echo "$dir/$(basename "$target")"
    else
        # Find nearest existing ancestor
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

# --- 1. Path Containment & Boundary Verification ---
is_same_or_inside() {
    local child="$1"
    local parent="$2"
    case "$child" in
        "$parent"|"$parent"/*) return 0 ;;
        *) return 1 ;;
    esac
}

if is_same_or_inside "$PROJECT_ROOT" "$SKILL_ROOT"; then
    echo "Error: Project root ('$PROJECT_ROOT') cannot be equal to or inside skill root ('$SKILL_ROOT')." >&2
    exit 1
fi
if is_same_or_inside "$SKILL_ROOT" "$PROJECT_ROOT"; then
    echo "Error: Skill root ('$SKILL_ROOT') cannot be inside project root ('$PROJECT_ROOT')." >&2
    exit 1
fi

VAULT_TEMPLATE_DIR="$SKILL_ROOT/assets/vault-template"
CONFIG_TEMPLATE_PATH="$SKILL_ROOT/assets/config-template.json"
SCHEMA_TEMPLATE_PATH="$SKILL_ROOT/assets/project-config.schema.json"

if [ ! -d "$VAULT_TEMPLATE_DIR" ]; then
    echo "Error: Vault template directory not found at $VAULT_TEMPLATE_DIR" >&2
    exit 1
fi
if [ ! -f "$CONFIG_TEMPLATE_PATH" ]; then
    echo "Error: Config template not found at $CONFIG_TEMPLATE_PATH" >&2
    exit 1
fi

PROJECT_RUNTIME_DIR="$PROJECT_ROOT/.it-department"
PROJECT_CONFIG_PATH="$PROJECT_RUNTIME_DIR/config.json"
PROJECT_SCHEMA_PATH="$PROJECT_RUNTIME_DIR/project-config.schema.json"

# --- 2. Load or Parse Configuration using Structured Tool ---
VAULT_REL_PATH="vault"
SESSIONS_REL_PATH=".it-department/sessions"
WORKTREES_REL_PATH=".it-department/worktrees"
PROJECT_NAME_EFFECTIVE="$PROJECT_NAME_INPUT"
CTO_MODE_EFFECTIVE="VIRTUAL"
LEDGER_REL_PATH=".it-department/sessions/_usage/ledger"
HAS_EFFICIENCY="yes"

if [ -f "$PROJECT_CONFIG_PATH" ]; then
    echo "    Loading existing .it-department/config.json..."
    if [ "$JSON_ENGINE" = "python3" ] || [ "$JSON_ENGINE" = "python" ]; then
        READ_VALUES=$($JSON_ENGINE -c '
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    cfg = json.load(f)
p = cfg.get("paths", {})
print(p.get("vault_relative_path", "vault"))
print(p.get("sessions_relative_path", ".it-department/sessions"))
print(p.get("worktrees_relative_path", ".it-department/worktrees"))
print(cfg.get("project_name", "Project Workspace"))
print(cfg.get("cto_mode", "VIRTUAL"))
e = cfg.get("efficiency") or {}
print(e.get("ledger_path") or ".it-department/sessions/_usage/ledger")
print("yes" if cfg.get("efficiency") else "no")
' "$PROJECT_CONFIG_PATH")
    elif [ "$JSON_ENGINE" = "node" ]; then
        READ_VALUES=$(node -e '
const fs = require("fs");
const cfg = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const p = cfg.paths || {};
console.log(p.vault_relative_path || "vault");
console.log(p.sessions_relative_path || ".it-department/sessions");
console.log(p.worktrees_relative_path || ".it-department/worktrees");
console.log(cfg.project_name || "Project Workspace");
console.log(cfg.cto_mode || "VIRTUAL");
const e = cfg.efficiency || {};
console.log(e.ledger_path || ".it-department/sessions/_usage/ledger");
console.log(cfg.efficiency ? "yes" : "no");
' "$PROJECT_CONFIG_PATH")
    elif [ "$JSON_ENGINE" = "jq" ]; then
        VAULT_REL_PATH=$(jq -r '.paths.vault_relative_path // "vault"' "$PROJECT_CONFIG_PATH")
        SESSIONS_REL_PATH=$(jq -r '.paths.sessions_relative_path // ".it-department/sessions"' "$PROJECT_CONFIG_PATH")
        WORKTREES_REL_PATH=$(jq -r '.paths.worktrees_relative_path // ".it-department/worktrees"' "$PROJECT_CONFIG_PATH")
        PROJECT_NAME_EFFECTIVE=$(jq -r '.project_name // "Project Workspace"' "$PROJECT_CONFIG_PATH")
        CTO_MODE_EFFECTIVE=$(jq -r '.cto_mode // "VIRTUAL"' "$PROJECT_CONFIG_PATH")
        LEDGER_REL_PATH=$(jq -r '.efficiency.ledger_path // ".it-department/sessions/_usage/ledger"' "$PROJECT_CONFIG_PATH")
        HAS_EFFICIENCY=$(jq -r 'if .efficiency then "yes" else "no" end' "$PROJECT_CONFIG_PATH")
    fi

    if [ "$JSON_ENGINE" != "jq" ]; then
        IFS=$'\n' read -r -d '' VAULT_REL_PATH SESSIONS_REL_PATH WORKTREES_REL_PATH PROJECT_NAME_EFFECTIVE CTO_MODE_EFFECTIVE LEDGER_REL_PATH HAS_EFFICIENCY <<< "$READ_VALUES" || true
    fi
fi

# --- 3. Validate Relative Paths BEFORE Mutation ---
validate_subpath() {
    local rel="$1"
    local field="$2"
    if [ -z "$rel" ]; then
        echo "Error: Configuration path '$field' must not be empty." >&2
        exit 1
    fi
    case "$rel" in
        /*|[a-zA-Z]:*)
            echo "Error: Configuration path '$field' must be relative, got absolute: '$rel'" >&2
            exit 1
            ;;
        *..*)
            # Check traversal
            local resolved
            resolved="$(resolve_canonical "$PROJECT_ROOT/$rel")"
            if ! is_same_or_inside "$resolved" "$PROJECT_ROOT"; then
                echo "Error: Configuration path '$field' ('$rel') traverses outside project root." >&2
                exit 1
            fi
            ;;
    esac
    local full_path
    full_path="$(resolve_canonical "$PROJECT_ROOT/$rel")"
    if is_same_or_inside "$full_path" "$SKILL_ROOT"; then
        echo "Error: Configuration path '$field' ('$rel') resolves inside skill root." >&2
        exit 1
    fi
    echo "$full_path"
}

RESOLVED_VAULT_DIR=$(validate_subpath "$VAULT_REL_PATH" "paths.vault_relative_path")
RESOLVED_SESSIONS_DIR=$(validate_subpath "$SESSIONS_REL_PATH" "paths.sessions_relative_path")
RESOLVED_WORKTREES_DIR=$(validate_subpath "$WORKTREES_REL_PATH" "paths.worktrees_relative_path")
RESOLVED_LEDGER_DIR=$(validate_subpath "$LEDGER_REL_PATH" "efficiency.ledger_path")
RESOLVED_USAGE_DIR="$(dirname "$RESOLVED_LEDGER_DIR")"

echo "==> Initializing IT Department for Project: $PROJECT_NAME_EFFECTIVE"
echo "    Project Root: $PROJECT_ROOT"
echo "    Skill Root:   $SKILL_ROOT"

# --- 4. Mutate Filesystem Safely & Idempotently ---
mkdir -p "$PROJECT_RUNTIME_DIR" "$RESOLVED_SESSIONS_DIR" "$RESOLVED_WORKTREES_DIR" "$RESOLVED_VAULT_DIR" "$RESOLVED_LEDGER_DIR"

# Token optimizer: keep ledger/*.json (aggregates only); ignore raw transcript copies and audit runs
if [ ! -f "$RESOLVED_USAGE_DIR/.gitignore" ]; then
    printf '%s\n' \
        "# IT Department usage ledger: keep ledger/*.json (aggregates only); ignore raw transcript copies and audit runs" \
        "raw/" "audit-runs/" "audit-prompt.generated.md" > "$RESOLVED_USAGE_DIR/.gitignore"
fi

if [ -f "$SCHEMA_TEMPLATE_PATH" ] && [ ! -f "$PROJECT_SCHEMA_PATH" ]; then
    cp "$SCHEMA_TEMPLATE_PATH" "$PROJECT_SCHEMA_PATH"
fi

if [ ! -f "$PROJECT_CONFIG_PATH" ]; then
    echo "    Creating .it-department/config.json using structured $JSON_ENGINE serialization..."
    if [ "$JSON_ENGINE" = "python3" ] || [ "$JSON_ENGINE" = "python" ]; then
        $JSON_ENGINE -c '
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    cfg = json.load(f)
cfg["project_name"] = sys.argv[2]
with open(sys.argv[3], "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
' "$CONFIG_TEMPLATE_PATH" "$PROJECT_NAME_INPUT" "$PROJECT_CONFIG_PATH"
    elif [ "$JSON_ENGINE" = "node" ]; then
        node -e '
const fs = require("fs");
const cfg = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
cfg.project_name = process.argv[2];
fs.writeFileSync(process.argv[3], JSON.stringify(cfg, null, 2), "utf8");
' "$CONFIG_TEMPLATE_PATH" "$PROJECT_NAME_INPUT" "$PROJECT_CONFIG_PATH"
    elif [ "$JSON_ENGINE" = "jq" ]; then
        jq --arg name "$PROJECT_NAME_INPUT" '.project_name = $name' "$CONFIG_TEMPLATE_PATH" > "$PROJECT_CONFIG_PATH"
    fi
else
    echo "    Preserving existing .it-department/config.json."
fi

# Synchronize vault template idempotently
echo "    Synchronizing vault structure at: $RESOLVED_VAULT_DIR"
find "$VAULT_TEMPLATE_DIR" -type d | while read -r src_dir; do
    rel_dir="${src_dir#$VAULT_TEMPLATE_DIR}"
    if [ -n "$rel_dir" ]; then
        mkdir -p "$RESOLVED_VAULT_DIR$rel_dir"
    fi
done

find "$VAULT_TEMPLATE_DIR" -type f | while read -r src_file; do
    rel_file="${src_file#$VAULT_TEMPLATE_DIR}"
    target_file="$RESOLVED_VAULT_DIR$rel_file"
    if [ ! -f "$target_file" ]; then
        if [ "$(basename "$src_file")" = "00-Dashboard.md" ]; then
            CURRENT_DATE=$(date +%Y-%m-%d)
            sed -e "s/{PROJECT_NAME}/$PROJECT_NAME_EFFECTIVE/g" \
                -e "s/{LAST_UPDATED}/$CURRENT_DATE/g" \
                -e "s/{CTO_MODE}/$CTO_MODE_EFFECTIVE/g" \
                "$src_file" > "$target_file"
        else
            cp "$src_file" "$target_file"
        fi
    fi
done

echo "==> Initialization completed successfully."
echo "    Vault:     $RESOLVED_VAULT_DIR"
echo "    Sessions:  $RESOLVED_SESSIONS_DIR"
echo "    Worktrees: $RESOLVED_WORKTREES_DIR"
echo "    Ledger:    $RESOLVED_LEDGER_DIR"
if [ "$HAS_EFFICIENCY" != "yes" ]; then
    echo "    [HINT] config.json has no 'efficiency' block: the token optimizer uses default limits and paths. Copy the block from '$CONFIG_TEMPLATE_PATH' to tune rules R1-R5 and the audit interval."
fi
