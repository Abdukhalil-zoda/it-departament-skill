# Changelog

All notable changes to the IT Department skill. Versions follow [semantic versioning](https://semver.org): a
new role, workflow or script is a minor bump; a change that requires a project migration says so under
**Migration**; breaking changes to the config contract or the vault layout are a major bump. The version
lives in `VERSION`, `.claude-plugin/plugin.json` and the `metadata.version` field of `SKILL.md`; every merged
pull request bumps it and tags `v<version>` on `master`. `scripts/update-skill.{ps1,sh}` prints the entries
between the installed and the new version after an update, so the **Migration** notes are what a project
has to do by hand.

## [1.2.0] - 2026-10-07

### Added
- Claude Code plugin manifest (`.claude-plugin/plugin.json`) and a marketplace in the same repository
  (`.claude-plugin/marketplace.json`), so the skill installs and updates with `/plugin` commands and can
  auto-update per marketplace setting.
- Slash commands shipped with the plugin: `/it-department-skill:update-skill`,
  `/it-department-skill:validate-project`, `/it-department-skill:sync-dashboard`.
- Role files carry agent frontmatter (`name`, `description`), so the plugin exposes the eight roles as
  sub-agents; the files stay readable as role prompts for other hosts.
- `scripts/update-skill.ps1` / `.sh`: detects how the skill is installed (git checkout, Agent Skills CLI copy
  under `.agents/skills`, Claude Code plugin cache, plain copy), updates it, prints the changelog entries
  between the old and the new version, re-runs `init-project` and `validate-project` on the project.
- `VERSION`, this changelog, `metadata.version` in `SKILL.md`; `validate-project` prints the installed version.

### Changed
- `init-project` and `validate-project` accept a skill installed inside the project when it sits in a standard
  skills folder (`<project>/.agents/skills/<name>` or `<project>/.claude/skills/<name>`), which is where
  `npx skills add` puts it; any other nesting is still rejected.

### Migration
- Projects: none. Optional: `scripts/update-skill.ps1 -Check` (or `.sh --check`) tells whether upstream is newer.
- Claude Code users: `/plugin marketplace add Abdukhalil-zoda/it-department-skill`, then
  `/plugin install it-department-skill@it-department` (README "Installing and updating").

## [1.1.0] - 2026-10-07

### Added
- Operating profiles `prototype` / `pilot` / `production` (`operating_profile`, `profile_review` in
  `config.json`; `workflows/operating-profiles.md`; SKILL.md section 10): every gate scales with the profile;
  floors that never relax; the documented "experiment in prod" path for early profiles.
- Session protocol with a hand-written lock file and hand-off note (`workflows/session-protocol.md`).
- `scripts/dashboard_sync.py`: generated dashboard blocks between `<!-- sync:* -->` markers, every id a wikilink,
  "Tokens & Machine Time" block, usage-audit, content-review, release and documents sections.
- `scripts/apply_transitions.py`: applies `transition-request.json` files with lifecycle validation and a
  Transition Log in the note.
- `references/definition-of-ready-done.md`, decisions journal (`03-ADR/decisions-log.md`,
  `templates/decision-record.md`), `templates/qa-report.md`.
- `scripts/vault_lint.py` (VL001–VL014), run by `validate-project` when Python 3.8+ is available.

### Changed
- Task template: `docs:` frontmatter list and a `## 10. Transition Log` section; usage-audit report section 7
  gained a `Decision` column; `init-project` writes `.it-department/.gitignore` and fills the decisions journal
  placeholders; `documents` in the config template defaults to `[]`.

### Migration
- Re-run `init-project` (adds `vault/03-ADR/decisions-log.md` and `.it-department/.gitignore`).
- Add `operating_profile` and `profile_review` to `config.json` from `assets/config-template.json`; without
  them the project runs as `production`. Record the profile decision as `D-001` in the decisions journal.
- Run `scripts/dashboard_sync.py --root <project>` once: it inserts the sync markers into an existing dashboard
  and keeps hand-written text outside them.
- Run `scripts/vault_lint.py --root <project>` and fix the findings; `validate-project` now fails on lint errors.

## [1.0.0] - 2026-10-07

### Added
- Token optimizer: efficiency rules R1–R5 in every role file and task brief, `scripts/usage_ledger.py`
  (per-session usage ledger), `scripts/usage_report.py` (audit report with rule indicators and delta),
  `templates/usage-audit-prompt.md`, `scripts/schedule-usage-audit.{ps1,sh}`, `efficiency` config block,
  `vault/05-Reports/`.
- Content & Localization Reviewer role with two checkpoints (`agents/content-reviewer.md`,
  `workflows/content-review.md`, `templates/content-review-report.md`), `scripts/content_inventory.py`,
  `content_review` config block, `vault/06-Content/` glossary and style guide.
- `README.md`, `.gitattributes` (LF for scripts).

### Migration
- Re-run `init-project` (adds `vault/05-Reports/`, `vault/06-Content/`, `sessions/_usage/`).
- Copy the `efficiency` and `content_review` blocks from `assets/config-template.json` into `config.json`;
  for multilingual products set `content_review.source_locale` and `locales`.

## [0.9.0] - 2026-09-18

### Added
- Initial package: eight-step delivery pipeline, role prompts, workflows, task / bug / ADR templates, vault
  template, idempotent `init-project` and `validate-project` scripts.
