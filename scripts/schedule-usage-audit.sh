#!/usr/bin/env bash
# Renders the usage-audit prompt for a project and runs or schedules it headlessly with the Claude Code CLI.
# Part of the IT Department skill token optimizer (workflows/efficiency-and-usage-audit.md, section 5B).
#
#   schedule-usage-audit.sh <project-root> [--skill-root DIR] [--dry-run | --run-now | --register]
#                           [--interval-days N] [--at HH:MM] [--model ID] [--claude PATH]
#
#   --dry-run   (default) print the rendered prompt path, the claude command and the cron line
#   --run-now   run one audit now:  claude -p ... < prompt   (cwd = project root)
#   --register  add/replace a crontab line that runs this script with --run-now every N days at --at
#               (cron "*/N" on day-of-month: fires on days 1, 1+N, ...; month ends may give a 1- or 3-day gap)
#
# Prerequisites for --run-now/--register: claude CLI logged in, python3 on PATH, project transcripts in
# ~/.claude/projects (the audit rebuilds the ledger from them). Python is used to read config.json.
set -euo pipefail

usage() { sed -n '2,13p' "$0" >&2; exit 2; }
[ "$#" -ge 1 ] || usage

PROJECT_ROOT_INPUT="$1"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="dry-run"; INTERVAL_OVERRIDE=""; AT="08:30"; MODEL_OVERRIDE=""; CLAUDE="claude"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --skill-root) SKILL_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
        --dry-run) MODE="dry-run"; shift ;;
        --run-now) MODE="run-now"; shift ;;
        --register) MODE="register"; shift ;;
        --interval-days) INTERVAL_OVERRIDE="$2"; shift 2 ;;
        --at) AT="$2"; shift 2 ;;
        --model) MODEL_OVERRIDE="$2"; shift 2 ;;
        --claude) CLAUDE="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Error: Python 3.8+ is required (reads config.json, runs the usage scripts)." >&2; exit 1; }

[ -d "$PROJECT_ROOT_INPUT" ] || { echo "Error: ProjectRoot not found: $PROJECT_ROOT_INPUT" >&2; exit 1; }
PROJECT_ROOT="$(cd "$PROJECT_ROOT_INPUT" && pwd -P)"
CONFIG="$PROJECT_ROOT/.it-department/config.json"
TEMPLATE="$SKILL_ROOT/templates/usage-audit-prompt.md"
[ -f "$CONFIG" ] || { echo "Error: missing $CONFIG - run init-project first." >&2; exit 1; }
[ -f "$TEMPLATE" ] || { echo "Error: skill package error, $TEMPLATE not found." >&2; exit 1; }
echo "$AT" | grep -Eq '^[0-9]{1,2}:[0-9]{2}$' || { echo "Error: --at must be HH:MM" >&2; exit 1; }

# --- 1. Settings from config.json (one value per line) ----------------------------------------------------
SETTINGS="$("$PY" - "$CONFIG" "$PROJECT_ROOT" <<'PYEOF'
import json, os, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
eff = cfg.get("efficiency") or {}
if not eff:
    print("WARN: config.json has no 'efficiency' block - using defaults", file=sys.stderr)
print(eff.get("audit_interval_days") or 2)
print(eff.get("audit_model") or "claude-fable-5-1")
print(eff.get("report_language") or "en")
print(eff.get("ledger_path") or ".it-department/sessions/_usage/ledger")
print(eff.get("reports_path") or "vault/05-Reports")
print((cfg.get("paths") or {}).get("vault_relative_path") or "vault")
print((cfg.get("git_policy") or {}).get("integration_branch") or "development")
print(cfg.get("project_name") or os.path.basename(sys.argv[2]))
PYEOF
)"
INTERVAL="$(echo "$SETTINGS" | sed -n 1p)"; MODEL="$(echo "$SETTINGS" | sed -n 2p)"; LANGUAGE="$(echo "$SETTINGS" | sed -n 3p)"
LEDGER_PATH="$(echo "$SETTINGS" | sed -n 4p)"; REPORTS_PATH="$(echo "$SETTINGS" | sed -n 5p)"; VAULT_PATH="$(echo "$SETTINGS" | sed -n 6p)"
BRANCH="$(echo "$SETTINGS" | sed -n 7p)"; PROJECT_NAME="$(echo "$SETTINGS" | sed -n 8p)"
[ -n "$INTERVAL_OVERRIDE" ] && INTERVAL="$INTERVAL_OVERRIDE"
[ -n "$MODEL_OVERRIDE" ] && MODEL="$MODEL_OVERRIDE"
echo "$INTERVAL" | grep -Eq '^[0-9]+$' && [ "$INTERVAL" -ge 1 ] || { echo "Error: interval must be a positive integer" >&2; exit 1; }

# --- 2. Render the prompt ----------------------------------------------------------------------------------
USAGE_DIR="$PROJECT_ROOT/$(dirname "$LEDGER_PATH")"
RUNS_DIR="$USAGE_DIR/audit-runs"
PROMPT_PATH="$USAGE_DIR/audit-prompt.generated.md"
mkdir -p "$USAGE_DIR" "$RUNS_DIR"
"$PY" - "$TEMPLATE" "$PROMPT_PATH" "$PROJECT_NAME" "$PROJECT_ROOT" "$SKILL_ROOT" "$BRANCH" "$VAULT_PATH" "$LEDGER_PATH" "$REPORTS_PATH" "$INTERVAL" "$LANGUAGE" <<'PYEOF'
import re, sys
(template, out, name, root, skill, branch, vault, ledger, reports, interval, language) = sys.argv[1:12]
text = open(template, encoding="utf-8").read()
m = re.search(r"```text\r?\n(.*?)\r?\n```", text, re.S)
if not m:
    sys.exit("Could not find the prompt block (```text fence) in " + template)
prompt = m.group(1)
refresh = ("Run `python3 {SKILL_ROOT}/scripts/usage_ledger.py --root {PROJECT_ROOT}`; it reads this project's transcripts "
           "from ~/.claude/projects and rewrites `{PROJECT_ROOT}/{LEDGER_PATH}` (idempotent).")
prompt = prompt.replace("{LEDGER_REFRESH_STEP}", refresh)
for k, v in {"{PROJECT_NAME}": name, "{PROJECT_ROOT}": root, "{SKILL_ROOT}": skill, "{INTEGRATION_BRANCH}": branch,
             "{VAULT_PATH}": vault, "{LEDGER_PATH}": ledger, "{REPORTS_PATH}": reports,
             "{AUDIT_INTERVAL_DAYS}": interval, "{REPORT_LANGUAGE}": language}.items():
    prompt = prompt.replace(k, v)
left = sorted(set(re.findall(r"\{[A-Z_]+\}", prompt)))
if left:
    sys.exit("Unfilled placeholders in the prompt: " + ", ".join(left))
open(out, "w", encoding="utf-8").write(prompt)
PYEOF

# --- 3. The headless command -------------------------------------------------------------------------------
ALLOWED='Read Write Edit MultiEdit Glob Grep Bash(python *) Bash(python3 *) Bash(git add *) Bash(git commit *) Bash(git status *) Bash(git log *) Bash(git diff *) Bash(git rev-parse *) Bash(git branch *) Bash(ls *) Bash(cat *)'
CMD_DISPLAY="$CLAUDE -p --model $MODEL --permission-mode acceptEdits --allowedTools \"$ALLOWED\" --add-dir \"$SKILL_ROOT\" --output-format text < \"$PROMPT_PATH\""
HOUR="${AT%%:*}"; MINUTE="${AT##*:}"
CRON_LINE="$((10#$MINUTE)) $((10#$HOUR)) */$INTERVAL * * cd \"$PROJECT_ROOT\" && \"$SCRIPT_DIR/schedule-usage-audit.sh\" \"$PROJECT_ROOT\" --skill-root \"$SKILL_ROOT\" --run-now >> \"$RUNS_DIR/cron.log\" 2>&1 # it-departament-usage-audit:$PROJECT_ROOT"

echo "==> IT Department usage audit (headless)"
echo "    Project:   $PROJECT_ROOT ($PROJECT_NAME)"
echo "    Skill:     $SKILL_ROOT"
echo "    Model:     $MODEL   Interval: every $INTERVAL day(s) at $AT   Language: $LANGUAGE"
echo "    Prompt:    $PROMPT_PATH"
echo "    Command:   $CMD_DISPLAY"
echo "    Cron line: $CRON_LINE"

case "$MODE" in
    run-now)
        command -v "$CLAUDE" >/dev/null 2>&1 || { echo "Error: claude CLI not found ('$CLAUDE'). Install Claude Code or pass --claude." >&2; exit 1; }
        LOG="$RUNS_DIR/$(date +%Y-%m-%d_%H%M%S).log"
        echo "==> Running audit now; output -> $LOG"
        (cd "$PROJECT_ROOT" && "$CLAUDE" -p --model "$MODEL" --permission-mode acceptEdits --allowedTools "$ALLOWED" \
            --add-dir "$SKILL_ROOT" --output-format text < "$PROMPT_PATH" 2>&1 | tee "$LOG")
        echo "==> Audit finished; report under $REPORTS_PATH"
        ;;
    register)
        command -v crontab >/dev/null 2>&1 || { echo "Error: crontab not available on this system." >&2; exit 1; }
        MARK="# it-departament-usage-audit:$PROJECT_ROOT"
        EXISTING="$(crontab -l 2>/dev/null || true)"
        { echo "$EXISTING" | grep -vF "$MARK" || true; echo "$CRON_LINE"; } | sed '/^$/d' | crontab -
        echo "==> crontab entry installed (every $INTERVAL day(s) at $AT). Keep efficiency.audit_interval_days in config.json equal to $INTERVAL."
        echo "    Remove with: crontab -l | grep -vF '$MARK' | crontab -"
        ;;
    *)
        echo "==> Dry run only. Use --run-now to audit now or --register to install the cron line."
        ;;
esac
