---
name: kmp-dev-machine-cleanup
description: Use when a macOS machine used for Kotlin Multiplatform, Android or iOS development is slow, swapping, or out of disk - "Mac is slow", "free RAM", "free disk space", "clean caches", "disk full", Xcode DerivedData or iOS DeviceSupport huge, CoreSimulator taking gigabytes, old ~/.gradle or ~/.konan versions, stale Gradle/Kotlin daemons, emulators or simulators left running.
license: Apache-2.0
compatibility: macOS with zsh or bash. Uses only built-in tools plus xcrun, adb, brew and npm when installed. Deletes files only after explicit user approval.
metadata:
  category: tooling
  platforms: android, ios
---

# KMP dev machine cleanup (macOS)

Measure, report, ask, then clean only what the user approved, and measure again. Everything
targeted here is regenerable — caches, old toolchains, stale processes — but "regenerable" still
costs a re-download or a cold build, and a few look like caches while holding real data (archives
with dSYMs, emulator images with logged-in accounts, locally published libraries). Nothing is
killed or deleted before the user says yes to that specific item.

## When to use

- Memory pressure is high, swap is large, or the machine stalls during Gradle or Xcode builds.
- Free disk is low, or Xcode, Android Studio or the simulator complain about space.
- A periodic (for example monthly) tidy-up of a KMP/Android/iOS workstation.

## When not to use

- A build is slow but the machine is fine: use `kmp-build-failure-triage` or the Kotlin native
  build performance skill linked below.
- Cleaning a **project's** build outputs: `./gradlew clean` in that project is enough.
- CI runners: they are ephemeral; fix caching in the workflow (`kmp-ci-github-actions`).

## Step 0 — Read the machine first

Find out what the user works on before deciding what is "unused".

```bash
sw_vers; uname -m                                  # macOS version, arm64 or x86_64
echo "$SHELL"                                      # zsh does not word-split unquoted $vars (see below)
ls /Applications | grep -iE 'xcode|android studio|intellij|fleet'
xcode-select -p
```

Ask the user which directories hold their projects (for example `$HOME/dev`). You need them to
know which Gradle, Kotlin/Native and SDK versions are still in use:

```bash
PROJECT_ROOTS=("$HOME/dev")          # replace with the user's answer
for r in "${PROJECT_ROOTS[@]}"; do
  find "$r" -maxdepth 4 -name gradle-wrapper.properties -path '*gradle/wrapper/*' -print0 2>/dev/null | xargs -0 grep -ho 'gradle-[0-9.]*-'
done | sort -u                                                   # Gradle versions in use
for r in "${PROJECT_ROOTS[@]}"; do
  find "$r" -maxdepth 4 -name libs.versions.toml -print0 2>/dev/null | xargs -0 grep -hE '^kotlin *='
done | sort -u                                                   # Kotlin versions in use
```

## Workflow

### 1. Measure

```bash
sysctl vm.swapusage
memory_pressure | tail -n 1                                       # "System-wide memory free percentage"
vm_stat | awk '/page size of/{ps=$8} /Pages free/{f=$3} /occupied by compressor/{c=$5} END{printf "free %.1f GB  compressed %.1f GB\n", f*ps/1e9, c*ps/1e9}'
df -h /System/Volumes/Data | tail -n 1
top -l 1 -o mem -n 25 -stats pid,command,mem | tail -n 26
```

Write the numbers down: they are the "before" column of the final report. Rough signals that a
cleanup is worth it: swap in the many-gigabyte range, memory free percentage persistently low, or
free disk under roughly 10–15 % of the volume.

### 2. Find stale processes (RAM)

**First, protect the current session.** List this shell's ancestry and never kill anything in it
(the terminal, IDE or agent session running these commands):

```bash
p=$$; while [ "$p" -gt 1 ]; do ps -o pid=,ppid=,etime=,command= -p "$p" | cut -c1-140; p=$(ps -o ppid= -p "$p" | tr -d ' '); done
```

Then list candidates with age (`etime`) and memory (`rss`, KB):

```bash
ps -axo pid,etime,rss,command | grep -E 'GradleDaemon|KotlinCompileDaemon|kotlin-daemon' | grep -v grep
ps -axo pid,etime,rss,command | grep -E 'qemu-system|emulator' | grep -v grep           # Android emulators
xcrun simctl list devices booted                                                          # booted simulators
ps -axo pid,etime,rss,command | grep -E 'vite|next dev|webpack|http-server|json-server' | grep -v grep
ps -axo pid,etime,rss,command | grep -E 'mcp|npx|uvx' | grep -v grep | head -40          # agent tool servers
```

| Candidate | Stop it with | Note |
|---|---|---|
| Gradle daemons | `./gradlew --stop` in a project (stops daemons of that Gradle version), or `kill -TERM <pid>` | Several versions can run at once; each holds GBs |
| Kotlin compile daemons | `kill -TERM <pid>` | Restart on the next build |
| Android emulator | `adb emu kill` (or `adb -s emulator-5554 emu kill`) | Unsaved emulator state is lost |
| Booted simulators | `xcrun simctl shutdown all` | Safe; apps stay installed |
| Old dev servers | `kill -TERM <pid>` | Their command lines can contain secrets — do not echo them back; just flag the PID |
| Old terminal / coding-agent sessions and their tool-server children | `kill -TERM` the session's process tree | Ask separately about anything younger than about two days: it may be an open tab |

Kill trees safely. In **zsh**, an unquoted `$list` is passed as one argument, so `kill $pids`
silently does nothing useful — use an array:

```bash
descendants() { local p=$1; for c in $(pgrep -P "$p"); do descendants "$c"; done; echo "$p"; }
pids=()                                   # build from the approved roots, minus the ancestry list
for root in 12345 23456; do pids+=($(descendants "$root")); done
kill -TERM "${pids[@]}"
ps -p "${(j:,:)pids}" 2>/dev/null          # zsh; in bash: ps -p "$(IFS=,; echo "${pids[*]}")"
```

Escalate to `kill -KILL` only for processes that survive `TERM`, and only after telling the user.

### 3. Size the regenerable caches (disk)

Report sizes first; delete nothing in this step. `NULL_GLOB` stops zsh from aborting on a
pattern with no matches (bash ignores the line).

```bash
setopt NULL_GLOB 2>/dev/null
cd "$HOME" && for d in \
  Library/Developer/Xcode/DerivedData \
  "Library/Developer/Xcode/iOS DeviceSupport" \
  Library/Developer/Xcode/Archives \
  Library/Developer/CoreSimulator/Devices \
  Library/Developer/CoreSimulator/Caches \
  Library/Caches/org.swift.swiftpm \
  Library/Caches/CocoaPods \
  Library/Caches/Google \
  Library/Caches/JetBrains \
  Library/Caches/Homebrew \
  .gradle/caches .gradle/wrapper/dists .gradle/daemon \
  .konan .m2/repository .android/avd .npm \
  Library/Android/sdk/system-images ; do
  [ -e "$d" ] && printf '%8s  %s\n' "$(du -sh "$d" 2>/dev/null | cut -f1)" "$d"
done
du -sh "$HOME"/Library/Caches/Google/AndroidStudio* "$HOME"/.gradle/caches/[0-9]* \
  "$HOME"/.gradle/wrapper/dists/* "$HOME"/.konan/kotlin-native-prebuilt-* 2>/dev/null
xcrun simctl runtime list 2>/dev/null          # installed simulator runtimes (often several GB each)
xcrun simctl list devices unavailable
```

### 4. Check before each deletion

| Item | Check first | Remove |
|---|---|---|
| Xcode DerivedData | Nothing important; next build is cold | `rm -rf "$HOME/Library/Developer/Xcode/DerivedData/"*` |
| iOS DeviceSupport | Keep the newest entry for each device/OS still in use | Older folders; Xcode recreates them on connect |
| Xcode Archives | **Holds dSYMs** needed to symbolicate crashes of shipped builds | Only archives whose dSYMs are uploaded or stored elsewhere — ask per archive |
| Unavailable simulators | none | `xcrun simctl delete unavailable` |
| Simulator runtimes | `xcrun simctl list devices` — the remaining runtimes still cover the devices the user tests on | `xcrun simctl runtime delete <identifier>` |
| Android Studio caches `~/Library/Caches/Google/AndroidStudio*` | Which folder the **running** Studio uses — it is not always the newest (command below) | Older folders; keep the in-use one and the newest. Old `~/Library/Logs/Google/AndroidStudio*` too |
| Android Studio settings `~/Library/Application Support/Google/AndroidStudio*` | Contains settings and plugins | Only versions no longer installed; ask |
| Gradle version caches `~/.gradle/caches/<version>/` and `~/.gradle/wrapper/dists/gradle-<version>-*` | Versions from Step 0 | Versions no project uses. Gradle also prunes unused versions itself over time |
| Gradle shared caches `~/.gradle/caches/modules-2`, `build-cache-1`, `transforms-*`, `jars-*` | Deleting forces every project to re-download and rebuild | Leave them unless disk is critical; then remove only with the user's explicit OK and no Gradle running |
| Gradle daemon logs `~/.gradle/daemon/<version>/` | none | Old versions' folders |
| Kotlin/Native `~/.konan/kotlin-native-prebuilt-*-<version>` | Kotlin versions from Step 0 | Unused versions; the next build of that Kotlin version re-downloads |
| `~/.m2/repository` | May hold the user's own `publishToMavenLocal` libraries | Ask; never by default |
| Android SDK system images / old build-tools | `sdkmanager --list_installed`; which AVDs use which image | `sdkmanager --uninstall "<package path>"` |
| AVDs `~/.android/avd/*.avd` | Contain app data and test logins | Ask per AVD; prefer "Wipe data" in Device Manager |
| CocoaPods / SwiftPM caches | none | `pod cache clean --all`; remove `~/Library/Caches/org.swift.swiftpm` |
| Homebrew | none | `brew cleanup -n` (dry run), then `brew cleanup -s --prune=all` |
| npm | none | `npm cache verify`, then `npm cache clean --force` |

Which Android Studio cache folder is in use (run while Studio is open):

```bash
lsof -p "$(pgrep -f 'Android Studio.app/Contents/MacOS/studio' | head -n 1)" 2>/dev/null \
  | grep -o 'Caches/Google/AndroidStudio[^/]*' | sort -u
```

Never touch: anything inside project repositories (other than via that project's own `clean`),
keychains, `~/.ssh`, `~/.gnupg`, IDE settings without asking, a coding agent's session history or
memory store, and any directory you do not recognise — report it instead.

### 5. Ask

Present two lists with sizes (or process counts and RSS) and let the user tick items:

- **Free RAM:** stale daemons, emulator, booted simulators, old sessions (recent ones listed separately).
- **Free disk:** Xcode leftovers, simulator runtimes, Android Studio caches, unused Gradle and
  Kotlin/Native versions, package-manager caches, optional large items (archives, AVDs, `~/.m2`).

Then show the exact commands you will run for the approved items (the dry run). Run them only after
the user confirms that list.

### 6. Clean, then re-measure

Run the approved commands one group at a time, checking each result (`ps -p`, `du -sh`). Then repeat
the Step 1 measurements and report:

| Metric | Before | After |
|---|---|---|
| Swap used | | |
| Memory free % | | |
| Free disk | | |
| Processes stopped | — | |

Recommend a restart when swap stays high after the cleanup — only a restart releases it reliably.
Name the top remaining memory users (usually the IDE and browsers) as the user's choice to close.
List everything skipped, and why (in use, not approved, still deleting in the background).

## Quick reference

| Goal | Command |
|---|---|
| Swap / pressure | `sysctl vm.swapusage` · `memory_pressure` (last line) |
| Free disk | `df -h /System/Volumes/Data` |
| Stop Gradle daemons | `./gradlew --stop` (per Gradle version) |
| Stop emulator | `adb emu kill` |
| Stop simulators | `xcrun simctl shutdown all` |
| Drop dead simulators | `xcrun simctl delete unavailable` |
| Simulator runtimes | `xcrun simctl runtime list` / `runtime delete <id>` |
| Brew | `brew cleanup -n` then `brew cleanup -s --prune=all` |
| Gradle versions in use | `grep -ho 'gradle-[0-9.]*-' <project>/gradle/wrapper/gradle-wrapper.properties` |
| Kotlin versions in use | `grep -hE '^kotlin *=' <project>/gradle/libs.versions.toml` |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` with the reason. Never mark a check PASS that you
did not run.

```bash
sysctl vm.swapusage; memory_pressure | tail -n 1; df -h /System/Volumes/Data | tail -n 1   # after numbers
ps -axo pid,command | grep -E 'GradleDaemon|KotlinCompileDaemon' | grep -v grep           # approved daemons gone
xcrun simctl list devices unavailable                                                      # expect none listed
ls "$HOME/.konan" "$HOME/.gradle/wrapper/dists"                                            # in-use versions still present
```

Finally, build one of the user's projects (`./gradlew help` at minimum) to prove the toolchain still
resolves. A cold first build afterwards is expected, not a failure.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Deleting before measuring | No before/after; no proof the cleanup helped | Step 1 first, always |
| Killing the current session's ancestors | The terminal or agent running the cleanup dies mid-way | Ancestry list first; exclude it |
| `kill $pids` in zsh | zsh does not word-split: one bogus argument, nothing killed, no error you notice | Arrays: `kill -TERM "${pids[@]}"` |
| Assuming the newest Android Studio cache is the live one | The running IDE may use an older folder; deleting it corrupts the session | Check with `lsof` |
| Deleting Xcode Archives as "caches" | dSYMs gone; production crashes can no longer be symbolicated | Ask per archive; keep shipped ones |
| Wiping `~/.gradle/caches` entirely | Every project re-downloads all dependencies | Remove only unused version folders |
| Removing a Kotlin/Native or Gradle version still in use | Next build re-downloads; offline work breaks | Derive versions from the user's projects |
| Clearing `~/.m2/repository` | Locally published snapshot libraries disappear | Ask |
| Deleting AVDs to save space | Test accounts and app data lost | Wipe data or ask per AVD |
| Echoing a dev server's command line | It may contain passwords or tokens | Report the PID and name only |

## Related skills

- `kmp-build-failure-triage` — builds that fail after a cleanup (usually a missing toolchain, re-downloaded on retry).
- `kmp-ci-github-actions` — caching on CI runners instead of local machines.
- External: [Kotlin native build performance skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-native-build-performance).
