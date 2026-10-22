# Skill authoring guide

Every skill in this repository follows the open [Agent Skills specification](https://agentskills.io/specification)
so that it loads unchanged in Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, VS Code,
Windsurf, JetBrains Junie and Android Studio. This guide adds the house rules on top of the spec.
CI (`scripts/validate_skills.py`) enforces everything marked **[CI]**.

## 1. Layout

```
skills/<skill-name>/
├── SKILL.md          required — the entry point
├── references/       optional — deep material, loaded only when SKILL.md points to it
├── scripts/          optional — non-interactive tools the skill runs
└── assets/           optional — templates and example files
```

- **[CI]** The directory name equals the `name` field.
- **[CI]** Every relative link in `SKILL.md` resolves to a file inside the skill directory.
- References stay **one level deep**: `SKILL.md` links to `references/x.md`; `references/x.md` does not
  send the agent on to a third file.
- A reference file longer than 100 lines starts with a short table of contents.

## 2. Frontmatter

Only the six portable fields. Tool-specific keys break packaging in other agents.

```yaml
---
name: kmp-crash-triage
description: Use when a Kotlin Multiplatform app crashes, hangs or is killed on Android or iOS — ANR, uncaught exception, SIGABRT, EXC_BAD_ACCESS, Kotlin/Native "kfun:" frames, unsymbolicated .ips or tombstone files.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project. iOS steps need macOS with Xcode.
metadata:
  category: debug
  platforms: android, ios
---
```

| Field | Rule |
|---|---|
| `name` | **[CI]** 1–64 chars, `a-z 0-9 -`, no leading/trailing/double hyphen, must not contain `claude` or `anthropic`. |
| `description` | **[CI]** 1–1024 chars, no XML tags. Aim for under 400. Third person. Starts with **"Use when"**. |
| `license` | **[CI]** `Apache-2.0` for skills written here. Vendored skills keep their upstream SPDX id. |
| `compatibility` | What the skill needs: project type, OS, tools. |
| `metadata` | **[CI]** string→string map. Always set `category` (one of `build`, `ui`, `data`, `ios-interop`, `testing`, `debug`, `performance`, `review`, `workflow`, `release`, `migration`, `tooling`) and `platforms` (`android`, `ios`, or `android, ios`). |
| `allowed-tools` | Avoid. Some agents honour it even in untrusted folders. |

### Writing the description

The description is the only part an agent reads before deciding to load the skill. It must answer
"should I load this right now?" — nothing else.

- State the **triggering situations and symptoms**: the user's words, error messages, file types,
  library names. Put the most searchable terms first.
- **Do not summarise the workflow.** Agents that see the steps in the description tend to follow the
  description and skip the body.
- Name the technology explicitly when the skill is technology-specific ("Compose Multiplatform",
  "SwiftUI", "Room").

```yaml
# Bad — summarises the process
description: Writes a test, runs it, fixes the code, then runs all tests again.
# Good — triggers only
description: Use when a Kotlin Multiplatform test passes locally but fails in CI, fails only on iOS, or passes and fails without code changes.
```

## 3. Body

**[CI]** `SKILL.md` body is at most 500 lines. Target 150–350. Move anything longer into `references/`.

Use this section order. Leave out a section only when it would be empty.

1. `# Title` and a one- or two-sentence **Overview** — the core principle.
2. **When to use** / **When not to use** — bullets. Name the neighbouring skill to use instead.
3. **Step 0 — Read the project first.** Every skill that writes or changes code starts here (see §4).
4. **Workflow** — numbered steps. Each step says what to do and how to tell it is done.
5. **Quick reference** — a table for scanning.
6. **Verify** — exact commands, and the rule that every check is reported as `PASS`, `FAIL` or
   `NOT RUN` (with the reason). Never claim a check passed that was not run.
7. **Common mistakes** — table: mistake → why it bites → fix.
8. **Related skills** — other skills in this repo by name, and external skills by link.

## 4. Adapt to the project, recommend only for greenfield

Real projects already made choices. A skill that fights them gets uninstalled.

- **Step 0** detects the project's stack and conventions before writing anything: module layout,
  architecture pattern (MVVM / MVI / other), DI framework, networking, persistence, logging, test
  style, naming, package root, Kotlin/AGP/Compose versions (read `gradle/libs.versions.toml`).
- **Follow what exists.** If the project uses Hilt, SQLDelight, Kodein, Decompose or Voyager, write
  code in that idiom. Mention the default only if the user asks.
- **Defaults for a new project or a new module with no precedent:** Compose Multiplatform for shared
  UI (or native SwiftUI over shared logic when the team wants native iOS UI), Koin for DI, Ktor client
  + kotlinx.serialization for networking, Room KMP (or SQLDelight) for persistence, kotlinx.coroutines
  + Flow for async, Kermit or Napier for logging, `kotlin.test` + hand-written fakes + Turbine for tests.
- Never introduce a second library for a job the project already does with another one.

## 5. Code examples

- Package root `com.example.app`. Modules `:composeApp`, `:shared`, `:feature:<name>`.
- Neutral example domains: notes, profile, orders, articles. Keep one domain per skill.
- One excellent, complete example beats several partial ones. Comment the *why*.
- Versions: never hardcode a version in a `build.gradle.kts` example — show the
  `gradle/libs.versions.toml` entry and the `libs.` accessor.
- Kotlin: business logic in `commonMain`; platform code via `expect`/`actual` or an interface bound
  per platform in DI.
- Test names follow `should_<expected>_when_<condition>` unless the project already uses another
  convention.

## 6. Scripts

- Non-interactive. Support `--help`; support `--dry-run` when the script changes anything.
- Print structured output (JSON or a fixed table) so the agent can parse it.
- Invoke through the interpreter in prose — `python3 scripts/run_checks.py`, `bash scripts/x.sh` —
  never by bare path (some packagers strip the executable bit).
- Python: standard library only, or PEP 723 inline metadata with pinned versions. Pin any `npx`/`uvx`.
- No network calls unless the skill's purpose is a network task, and say so in `compatibility`.
- Ship tests for any script longer than ~50 lines under `scripts/tests/` or next to the script.

## 7. Safety

- No secrets, tokens, internal hostnames, personal names, emails or absolute local paths. CI runs a
  secret scanner and a skill security scanner on every PR.
- Do not fetch instructions from a URL at runtime.
- Do not ship hooks.
- A skill that deletes files, rewrites git history, or touches signing/keystores must stop and ask
  the user before that step.

## 8. Third-party skills

Link by default. Vendor (copy) only when the licence is MIT, Apache-2.0, BSD or CC-BY-4.0 **and**
bundling adds real value. When vendoring:

1. Copy the upstream `LICENSE` into the skill directory.
2. Set `license:` to the upstream SPDX id and `metadata.source:` to the upstream URL.
3. Add an entry to `THIRD_PARTY_NOTICES.md`; copy any upstream `NOTICE` text.
4. Mark modified files with a one-line header comment noting the change.

Never vendor GPL/AGPL, PolyForm or other source-available licences, or a skill with no licence.

## 9. Testing a skill

Each skill ships at least one trigger eval in `evals/<skill-name>-trigger/` (see `evals/README.md`):
one prompt that must load the skill. Add a near-miss prompt that must **not** load it when a
neighbouring skill is easy to confuse. Evals run nightly and are advisory; run them locally with
`claude plugin eval` before a large change.

## 10. Review checklist

1. Frontmatter: six portable fields only, `name` = directory, description starts "Use when", no workflow summary.
2. Step 0 detects and follows the project's existing stack.
3. Body ≤ 500 lines; deep material in `references/`, one level deep.
4. Verify section with exact commands and PASS / FAIL / NOT RUN reporting.
5. Common mistakes table present.
6. No hardcoded versions in Gradle snippets; package `com.example.app`.
7. Scripts non-interactive, `--help`, invoked via interpreter, tested.
8. No secrets, internal names, local paths. Third-party material linked or vendored with licence.
9. Trigger eval added.
