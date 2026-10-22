# Installing KMP Mobile Skills

The skills are plain folders in the [Agent Skills](https://agentskills.io/specification) format, so you
can install them three ways:

1. **The `skills` CLI**: one command for any agent. Recommended if you use more than one tool.
2. **Your agent's own plugin or extension system**: Claude Code, Codex, Copilot CLI, VS Code and
   Gemini CLI can install the whole repo as a plugin.
3. **Copy or symlink** the folders into the directory your agent scans.

Install at **project level** (committed, so the whole team gets the skills) or **user level** (just
you, in every project). Project level is usually better for a team.

## Quick matrix

| Agent | Fastest install | Project folder it reads | User folder it reads |
|---|---|---|---|
| Claude Code | `/plugin marketplace add Kushpawan/kmp-mobile-skills` | `.claude/skills/` | `~/.claude/skills/` |
| OpenAI Codex | `codex plugin marketplace add Kushpawan/kmp-mobile-skills` | `.agents/skills/` | `~/.agents/skills/` |
| Cursor | `npx skills add Kushpawan/kmp-mobile-skills -a cursor` | `.agents/skills/`, `.cursor/skills/` | `~/.agents/skills/`, `~/.cursor/skills/` |
| Gemini CLI | `gemini extensions install https://github.com/Kushpawan/kmp-mobile-skills` | `.agents/skills/`, `.gemini/skills/` | `~/.agents/skills/`, `~/.gemini/skills/` |
| GitHub Copilot (CLI, cloud agent, IDEs) | `copilot plugin marketplace add Kushpawan/kmp-mobile-skills` | `.github/skills/`, `.agents/skills/`, `.claude/skills/` | `~/.copilot/skills/`, `~/.agents/skills/` |
| VS Code (Copilot chat) | setting `chat.plugins.marketplaces` (below) | `.github/skills/`, `.agents/skills/`, `.claude/skills/` | `~/.copilot/skills/`, `~/.agents/skills/` |
| Windsurf | `npx skills add Kushpawan/kmp-mobile-skills -a windsurf` | `.agents/skills/`, `.windsurf/skills/` | `~/.agents/skills/` |
| JetBrains Junie | `npx skills add Kushpawan/kmp-mobile-skills -a junie` | `.junie/skills/`, `.agents/skills/` | `~/.junie/skills/`, `~/.agents/skills/` |
| Android Studio (Gemini agent mode) | copy into `.agents/skills/` | `.agents/skills/`, `.android-studio/skills/` | same names under your home folder |

Agents change quickly. If a path or command here stops working, your agent's documentation is the
source of truth. Please open an issue so we can fix this page.

## 1. The `skills` CLI (any agent)

Needs Node.js 18+. The CLI is [vercel-labs/skills](https://github.com/vercel-labs/skills); it detects
installed agents and asks which skills to install.

```bash
# interactive: choose skills and target agents
npx skills add Kushpawan/kmp-mobile-skills

# see what the repo contains without installing
npx skills add Kushpawan/kmp-mobile-skills --list

# one skill, one agent, no prompts
npx skills add Kushpawan/kmp-mobile-skills --skill kmp-crash-triage -a cursor -y

# user level (all projects) instead of the current project
npx skills add Kushpawan/kmp-mobile-skills -g
```

Update or remove later with `npx skills update` and `npx skills remove`. Run `npx skills --help` for
every option. The CLI sends anonymous install telemetry; set `DISABLE_TELEMETRY=1` to opt out.

## 2. Plugin and extension systems

### Claude Code

```text
/plugin marketplace add Kushpawan/kmp-mobile-skills
/plugin install kmp-mobile-skills@kmp-mobile-skills
```

This installs every skill **and** the `kotlin-reviewer` / `swift-reviewer` subagents. Skills are
namespaced: call one directly with `/kmp-mobile-skills:<skill-name>`, or just describe the task.

To give the whole team the plugin, commit this to the project's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "kmp-mobile-skills": {
      "source": { "source": "github", "repo": "Kushpawan/kmp-mobile-skills" }
    }
  },
  "enabledPlugins": {
    "kmp-mobile-skills@kmp-mobile-skills": true
  }
}
```

Update with `/plugin marketplace update kmp-mobile-skills`. Third-party marketplaces do not
auto-update by default. Remove with `/plugin uninstall kmp-mobile-skills@kmp-mobile-skills`.

### OpenAI Codex

```bash
codex plugin marketplace add Kushpawan/kmp-mobile-skills
```

Then open `/plugins` inside Codex and install **KMP Mobile Skills**. The repo ships
`.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` for this.

### GitHub Copilot CLI

```bash
copilot plugin marketplace add Kushpawan/kmp-mobile-skills
copilot plugin install kmp-mobile-skills@kmp-mobile-skills
```

With the GitHub CLI 2.90 or later you can also install single skills (preview feature):

```bash
gh skill install Kushpawan/kmp-mobile-skills kmp-crash-triage --agent github-copilot --scope user
```

### VS Code

Add the repository as an agent plugin marketplace (experimental) in your settings:

```json
"chat.plugins.marketplaces": ["Kushpawan/kmp-mobile-skills"]
```

Or copy skills into `.github/skills/` or `.agents/skills/` (see section 3).

### Gemini CLI

```bash
gemini extensions install https://github.com/Kushpawan/kmp-mobile-skills
```

The extension manifest is `gemini-extension.json`; skills are picked up from `skills/`.

### Cursor, Windsurf, Junie, Android Studio

Use the `skills` CLI (section 1) or copy the folders (section 3). The repo also ships
`.cursor-plugin/plugin.json` for Cursor versions that install plugins from a GitHub repository.

### Xcode

Xcode 26.3+ can run third-party coding agents. Skill folder support there is new and not yet
documented by Apple. Community reports say the bundled Claude agent reads
`~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/skills/`. Treat this as unverified and
check your Xcode version's release notes.

## 3. Copy or symlink (any agent, no tooling)

```bash
git clone https://github.com/Kushpawan/kmp-mobile-skills.git ~/src/kmp-mobile-skills

# user level, for agents that read ~/.agents/skills (Codex, Cursor, Gemini, Copilot, Windsurf, Junie)
mkdir -p ~/.agents/skills
ln -s ~/src/kmp-mobile-skills/skills/* ~/.agents/skills/

# Claude Code reads ~/.claude/skills instead
mkdir -p ~/.claude/skills
ln -s ~/src/kmp-mobile-skills/skills/* ~/.claude/skills/

# Claude Code subagents (optional)
mkdir -p ~/.claude/agents
ln -s ~/src/kmp-mobile-skills/agents/*.md ~/.claude/agents/
```

For project level, copy the folders you want into the project's `.agents/skills/` (and
`.claude/skills/` for Claude Code) and commit them. Update with `git pull` in the clone.

Want only some skills? Symlink or copy just those folders. Each skill is self-contained, but some
skills name others in their "Related skills" section; the agent simply skips a related skill that is
not installed.

## Check that it works

Open a Kotlin Multiplatform project and ask:

> "Which skills do you have for Kotlin Multiplatform crashes?"

The agent should mention `kmp-crash-triage`. In Claude Code, `/plugin` lists the installed plugin
and `/kmp-mobile-skills:` autocompletes every skill.

## Requirements

- A Kotlin Multiplatform project built with Gradle (Kotlin 2.x recommended).
- iOS build, link and simulator steps need **macOS with Xcode**. On other systems those checks are
  reported as `NOT RUN`, never as passed.
- Scripts bundled in skills need **Python 3.10+** (standard library only).
