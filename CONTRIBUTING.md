# Contributing

Thanks for helping. This repo is useful only if every skill is correct, works in any Kotlin
Multiplatform project, and loads in every agent, so contributions go through a few checks.

## Ways to help

- **Report a skill that misbehaves**: wrong API, outdated advice, a step that fails, a skill that
  loads when it shouldn't (or doesn't load when it should). Use the *Skill bug* issue template and
  include the prompt you used and the agent/model.
- **Improve a skill**: a better example, a missing error message, a newer library version.
- **Propose a new skill**: open a *Skill request* issue first, so we can check it doesn't overlap
  an existing skill or a well-maintained external pack (see the README's "Works well with").

## Setup

You need Python 3.10+ (standard library only) and git. Nothing else is required to work on skills.

```bash
git clone https://github.com/Kushpawan/kmp-mobile-skills.git
cd kmp-mobile-skills
python3 scripts/validate_skills.py
```

To try your change in an agent, symlink the skill into your agent's skills folder (see
[INSTALL.md](INSTALL.md), section 3), or in Claude Code run `claude --plugin-dir .` from the repo root.

## Adding a skill

1. Read the [skill authoring guide](docs/skill-authoring-guide.md). It defines the frontmatter,
   section order, size limits and the "adapt to the project" rule every skill follows.
2. Create `skills/<skill-name>/SKILL.md`. The name is lowercase with hyphens and must match the
   folder. Prefix KMP-specific skills with `kmp-`, Compose Multiplatform skills with
   `compose-multiplatform-`, and skills that apply to any mobile app with `mobile-`.
3. Put long material in `references/`, runnable tools in `scripts/` (with tests), templates in
   `assets/`.
4. Add the trigger eval: write the user prompt that should load your skill into
   `evals/<skill-name>-trigger/prompt.md`, then run
   `python3 scripts/scaffold_trigger_eval.py <skill-name>` to add the run limits and the grader.
5. Run the checks below, then open a PR.

## Checks (run before every PR)

```bash
python3 scripts/validate_skills.py --strict   # frontmatter, size, links, evals
python3 scripts/sync_manifests.py             # update manifests + README catalog
python3 scripts/sync_manifests.py --check     # must print PASS
python3 scripts/run_tests.py                  # tests for repo and skill scripts
```

CI also runs a secret scanner and a skill security scanner. If you have Claude Code and an API key,
run the trigger evals for the skills you touched:

```bash
claude plugin eval . --trust-plugin --ablation none
```

## What reviewers look for

- **Correctness.** Real APIs, real Gradle tasks, real error messages. Cite the official docs in
  the PR description when you add or change a technical claim.
- **Generality.** No company, product or person names; no internal hostnames, paths or ticket
  ids. Examples use `com.example.app` and neutral domains (notes, profile, orders).
- **Follows the project.** Step 0 reads the user's project and follows its existing choices.
- **Both platforms.** Verification covers Android and iOS, with `PASS` / `FAIL` / `NOT RUN`.
- **Short.** `SKILL.md` stays under 500 lines; aim for 150–350.
- **Safe.** Scripts are non-interactive, have `--help`, and never delete, push or touch signing
  without asking.

## Third-party material

Prefer linking. To vendor (copy) a skill from another project, its licence must be MIT,
Apache-2.0, BSD or CC-BY-4.0; follow section 8 of the authoring guide and add it to
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Never copy GPL/AGPL, PolyForm or other
source-available content, or anything without a licence.

## Commit messages and releases

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat(kmp-crash-triage): add
dSYM upload check`, `fix(kmp-room-database): correct KSP target names`, `docs: …`, `ci: …`.

Maintainers release by updating [CHANGELOG.md](CHANGELOG.md), running
`python3 scripts/sync_manifests.py --version X.Y.Z`, committing, and pushing the tag `vX.Y.Z`.
The release workflow checks the manifests carry that version and publishes a GitHub release.

## Licence of contributions

By submitting a contribution you agree that it is licensed under the
[Apache License 2.0](LICENSE), the same licence as the project (section 5 of the licence).
You confirm you have the right to submit it. Do not submit code or text that your employer or
anyone else owns unless they have agreed to its release under this licence.

## Code of conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
