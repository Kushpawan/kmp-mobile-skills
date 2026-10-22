# Evals

Each folder here is one case for [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals).

## Trigger evals

`<skill-name>-trigger/` checks that a realistic request makes the agent **load** the skill:

```text
evals/kmp-crash-triage-trigger/
├── prompt.md                 frontmatter: run limits and tools; body: the user's request
└── graders/skill-fired.md    passes when the Skill tool loads kmp-crash-triage
```

Write the prompt the way a developer would type it inside their own project, without naming the
skill. Then run `python3 scripts/scaffold_trigger_eval.py <skill-name>` to add the frontmatter and
grader. `scripts/validate_skills.py` fails if a skill has no trigger eval.

## Running

Evals make real model calls on your account. Start with one case:

```bash
claude plugin eval . --trust-plugin --ablation none --case kmp-crash-triage-trigger
claude plugin eval . --trust-plugin --ablation none          # every case
```

Check `claude plugin eval --help` for the exact flags of your Claude Code version. Results go to
`evals/results/`, which is git-ignored.

The nightly **Evals** workflow runs every case when the repository has an `ANTHROPIC_API_KEY`
secret. It is advisory: a low score opens a discussion, it does not block merges.

## Adding outcome evals

A trigger eval proves the skill loads, not that it helps. For skills where it matters, add a case
that also grades the result, e.g. `kmp-room-database-ksp-targets/` with a `regex` grader over the
generated `build.gradle.kts`. Keep `llm` graders for short outputs with concrete PASS / FAIL
conditions.
