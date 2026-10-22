# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/): a new skill is a minor release, a fix to an existing
skill is a patch release, and renaming or removing a skill is a major release.

## [Unreleased]

## [0.1.0] - 2026-10-22

### Added

- First public set of Kotlin Multiplatform skills for Android and iOS, covering project and module
  setup, Compose Multiplatform UI, data layer, SwiftUI interop and XCFramework distribution, testing,
  crash / flaky-test / build-failure / performance triage, code, parity and security review, feature
  planning, CI, release, and Android-to-KMP migration.
- `kotlin-reviewer` and `swift-reviewer` subagents for Claude Code.
- Install manifests for Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot and VS Code.
- Trigger evals for every skill, plus validation, manifest-sync and test scripts with CI.
