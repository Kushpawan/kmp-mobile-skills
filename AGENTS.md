# Instructions for AI agents working on this repository

This file is for agents editing **this repo** (writing or fixing skills). It is not loaded by people
who install the skills.

- The rules for every skill are in [docs/skill-authoring-guide.md](docs/skill-authoring-guide.md).
  Read it before creating or editing anything under `skills/`.
- One skill per folder: `skills/<name>/SKILL.md`, where `name` in the frontmatter equals the folder
  name. Use only the six portable frontmatter keys.
- Every skill needs `evals/<name>-trigger/prompt.md`; run
  `python3 scripts/scaffold_trigger_eval.py <name>` after writing the prompt.
- Never hand-edit the skill lists in `.codex-plugin/plugin.json` / `.cursor-plugin/plugin.json` or
  the README catalog. Run `python3 scripts/sync_manifests.py`.
- Before you say a change is done, run and report:

  ```bash
  python3 scripts/validate_skills.py --strict
  python3 scripts/sync_manifests.py --check
  python3 scripts/run_tests.py
  ```

- Examples use `com.example.app` and neutral domains. Never add company, product or person names,
  internal hostnames, local paths, tokens or keys.
- Do not vendor third-party skills without following section 8 of the authoring guide.
