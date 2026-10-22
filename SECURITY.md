# Security policy

Agent skills are instructions and scripts that your AI agent follows on your machine, with your
permissions. Treat installing a skill like installing any other software: read it first.

## What we do

- Skills contain no secrets, no network calls (unless the skill's purpose needs one and says so in
  `compatibility`), no hooks and no instructions fetched from URLs at runtime.
- Scripts are non-interactive, support `--help`, and do not delete files, rewrite git history, push
  or touch signing material without the agent asking you first.
- Every pull request runs a secret scanner ([gitleaks](https://github.com/gitleaks/gitleaks)) and a
  skill security scanner ([Cisco AI Defense skill-scanner](https://github.com/cisco-ai-defense/skill-scanner)).
  A clean scan reduces risk but does not prove a skill is safe.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately through
**GitHub → Security → Report a vulnerability** on this repository (private vulnerability reporting).

Examples of what to report:

- a skill or script that leaks secrets or personal data, or sends data anywhere;
- instructions that could make an agent run destructive commands without asking;
- prompt-injection paths, e.g. a skill that tells the agent to obey text found in files or web pages;
- a compromised or malicious dependency in a bundled script.

We aim to acknowledge reports within 5 working days and to publish a fix or mitigation as fast as
the severity requires. We credit reporters in the release notes unless you ask us not to.

## Supported versions

Only the latest release receives fixes. Update with your agent's update command (see
[INSTALL.md](INSTALL.md)).
