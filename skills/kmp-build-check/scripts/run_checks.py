#!/usr/bin/env python3
"""Build and test a Kotlin Multiplatform repository for Android and iOS.

Every check ends in exactly one state:
  PASS     Gradle ran the task and exited 0
  FAIL     Gradle ran the task and exited non-zero
  NOT RUN  the check could not or should not run here; the reason is always given

Checks come from kmp-build-check.json at the repository root (see
assets/kmp-build-check.example.json), or are proposed by --detect.

Examples (run from the repository root, next to gradlew):
  python3 run_checks.py                          run every check in kmp-build-check.json
  python3 run_checks.py --dry-run                print the plan; run nothing
  python3 run_checks.py --base main              only checks the diff against origin/main can affect
  python3 run_checks.py --base-ref HEAD~3        the same, against an exact ref (no fetch)
  python3 run_checks.py --only ios --json -      iOS checks only; JSON on stdout
  python3 run_checks.py --detect gradle          propose a config from ./gradlew tasks --all
  python3 run_checks.py --detect static --write  propose a config from build files and save it

Exit status: 0 no check failed, 1 at least one FAIL, 2 bad usage or configuration.
A run with NOT RUN checks can exit 0 - read the summary before claiming success.
Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform as host_platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import unquote

CONFIG_NAME = "kmp-build-check.json"
PLATFORMS = ("any", "android", "ios")
KINDS = ("common", "android_build", "unit_test", "ios_compile", "ios_link", "ios_test", "other")
IOS_KINDS = ("ios_compile", "ios_link", "ios_test")
TASK_RE = re.compile(r"^(:[A-Za-z0-9_.\-]+)*:?[A-Za-z][A-Za-z0-9_]*$")
CHECK_KEYS = {"name", "platform", "task", "kind"}
CONSUMER_KEYS = {"name", "path", "task", "args", "platform", "kind"}
DEFAULT_TIMEOUT_MIN = 45
MARK = "[kmp-build-check]"


# -- data -------------------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    platform: str
    task: str
    kind: str
    directory: Path
    args: list = field(default_factory=list)
    consumer: str = ""
    not_run: str = ""
    scoped: bool = False


@dataclass
class Result:
    name: str
    platform: str
    task: str
    state: str                  # PASS | FAIL | NOT RUN
    reason: str = ""
    seconds: float = 0.0
    consumer: str = ""
    command: str = ""
    log: str = ""


# -- configuration ----------------------------------------------------------------------------

def infer_kind(task: str) -> str:
    """What a Gradle task proves, from its name. Used for scoping and host checks."""
    last = task.rsplit(":", 1)[-1]
    if last == "compileCommonMainKotlinMetadata":
        return "common"
    if re.match(r"^compile(Ios|Apple|Native|Darwin)\w*KotlinMetadata$", last):
        return "ios_compile"
    if "XCFramework" in last or re.match(r"^link\w*Framework\w*$", last):
        return "ios_link"
    if re.match(r"^compileKotlin(Ios|Tvos|Watchos|Macos)", last):
        return "ios_compile"
    if re.match(r"^(ios|tvos|watchos|macos)\w*Test$", last):
        return "ios_test"
    if re.match(r"^(test\w*UnitTest|testAndroidHostTest|jvmTest|desktopTest|test)$", last):
        return "unit_test"
    if re.match(r"^(assemble\w*|bundle\w*|compileAndroidMain|compile\w*KotlinAndroid)$", last):
        return "android_build"
    return "other"


def _validate_entry(entry, where: str, allowed: set, required: tuple) -> list:
    errors = []
    if not isinstance(entry, dict):
        return [f"{where}: must be an object"]
    unknown = {k for k in entry if k not in allowed and not k.startswith("_")}
    if unknown:
        errors.append(f"{where}: unknown key(s) {sorted(unknown)} (allowed: {sorted(allowed)}; prefix a key with _ for comments)")
    for k in required:
        if not isinstance(entry.get(k), str) or not entry.get(k).strip():
            errors.append(f"{where}: '{k}' must be a non-empty string")
    task = entry.get("task")
    if isinstance(task, str) and task and not TASK_RE.match(task):
        errors.append(f"{where}: task {task!r} is not a Gradle task path (e.g. :shared:jvmTest or jvmTest)")
    plat = entry.get("platform", "any")
    if plat not in PLATFORMS:
        errors.append(f"{where}: platform {plat!r} must be one of {list(PLATFORMS)}")
    kind = entry.get("kind")
    if kind is not None and kind not in KINDS:
        errors.append(f"{where}: kind {kind!r} must be one of {list(KINDS)}")
    return errors


def validate_config(cfg) -> list:
    """Every problem with the config, as readable strings. Empty list = valid."""
    if not isinstance(cfg, dict):
        return ["config: top level must be a JSON object"]
    errors = []
    unknown = {k for k in cfg if k not in {"version", "checks", "consumers"} and not k.startswith("_")}
    if unknown:
        errors.append(f"config: unknown key(s) {sorted(unknown)}")
    if cfg.get("version") != 1:
        errors.append("config: 'version' must be 1")
    checks = cfg.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("config: 'checks' must be a non-empty list")
        checks = []
    names = set()
    for i, c in enumerate(checks):
        errors += _validate_entry(c, f"checks[{i}]", CHECK_KEYS, ("name", "platform", "task"))
        if isinstance(c, dict) and c.get("name") in names:
            errors.append(f"checks[{i}]: duplicate name {c.get('name')!r}")
        if isinstance(c, dict):
            names.add(c.get("name"))
    consumers = cfg.get("consumers", [])
    if not isinstance(consumers, list):
        errors.append("config: 'consumers' must be a list")
        consumers = []
    for i, c in enumerate(consumers):
        errors += _validate_entry(c, f"consumers[{i}]", CONSUMER_KEYS, ("name", "path", "task"))
        args = c.get("args", []) if isinstance(c, dict) else []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            errors.append(f"consumers[{i}]: 'args' must be a list of strings, e.g. [\"-Plocal.mylib=true\"]")
    return errors


def load_config(path: Path):
    """(config, errors). A missing or unparsable file is an error, never an empty plan."""
    if not path.is_file():
        return None, [f"no config at {path} - create one with `--detect gradle --write`, "
                      f"or copy assets/kmp-build-check.example.json from the skill"]
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, [f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}"]
    return cfg, validate_config(cfg)


def build_checks(cfg: dict, project: Path, include_consumers: bool = True) -> list:
    checks = [Check(c["name"], c["platform"], c["task"], c.get("kind") or infer_kind(c["task"]), project)
              for c in cfg["checks"]]
    if include_consumers:
        for c in cfg.get("consumers", []):
            checks.append(Check(f"Consumer {c['name']}: {c['task']}", c.get("platform", "any"), c["task"],
                                c.get("kind") or infer_kind(c["task"]), (project / c["path"]).resolve(),
                                args=list(c.get("args", [])), consumer=c["name"]))
    return checks


# -- host environment -------------------------------------------------------------------------

def _run(cmd, cwd=None, timeout=60):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 127, "", "")


def ios_unavailable_reason(needs_simulator: bool) -> str:
    """Empty string when iOS checks can run here; otherwise why not."""
    if sys.platform != "darwin":
        return f"iOS checks need macOS with Xcode; this machine runs {host_platform.system() or sys.platform}"
    if not shutil.which("xcrun"):
        return "Xcode command-line tools not installed (xcrun not found)"
    if _run(["xcrun", "--find", "xcodebuild"]).returncode != 0:
        return "Xcode not installed or not selected (check `xcode-select -p`)"
    if needs_simulator:
        rt = _run(["xcrun", "simctl", "list", "runtimes"])
        if rt.returncode != 0 or "iOS" not in rt.stdout:
            return "no iOS simulator runtime installed (see `xcrun simctl list runtimes`)"
    return ""


def _default_sdks() -> list:
    home = Path.home()
    found = [home / "Library" / "Android" / "sdk", home / "Android" / "Sdk"]
    if os.environ.get("LOCALAPPDATA"):
        found.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
    return found


DEFAULT_SDKS = _default_sdks()


def android_sdk(directory: Path):
    """The Android SDK Gradle will use, or None: env var, then local.properties, then defaults."""
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(var)
        if value and Path(value).is_dir():
            return Path(value)
    props = directory / "local.properties"
    if props.is_file():
        for line in props.read_text(errors="replace").splitlines():
            if line.strip().startswith("sdk.dir="):
                value = re.sub(r"\\(.)", r"\1", line.split("=", 1)[1].strip())   # properties escaping
                return Path(value) if Path(value).is_dir() else None
    return next((d for d in DEFAULT_SDKS if d.is_dir()), None)


def gradle_wrapper(directory: Path):
    names = ("gradlew.bat", "gradlew") if os.name == "nt" else ("gradlew",)
    return next((directory / n for n in names if (directory / n).is_file()), None)


def _wrapper_cmd(wrapper: Path) -> list:
    # `sh gradlew` works even when the executable bit was lost (zip downloads, some checkouts).
    if wrapper.suffix == ".bat":
        return ["cmd", "/c", str(wrapper)]
    return ["sh", str(wrapper)]


def git_root(directory: Path):
    p = _run(["git", "rev-parse", "--show-toplevel"], cwd=directory)
    return Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None


def uninitialised_submodules(directory: Path) -> list:
    root = git_root(directory)
    if root is None or not (root / ".gitmodules").is_file():
        return []
    p = _run(["git", "submodule", "status"], cwd=root)
    return [line[1:].split(" ", 1)[1].strip() for line in p.stdout.splitlines()
            if line.startswith("-") and " " in line]


def untracked_sources(directory: Path) -> list:
    """Untracked .kt/.kts/.swift files. A build that includes them can PASS while the
    committed code - what CI and reviewers see - does not compile."""
    p = _run(["git", "ls-files", "--others", "--exclude-standard", "--", "*.kt", "*.kts", "*.swift"],
             cwd=directory)
    return [line for line in p.stdout.splitlines() if line.strip()] if p.returncode == 0 else []


# -- running Gradle ---------------------------------------------------------------------------

def run_gradle(directory: Path, task: str, args: list, log: Path, timeout_s: int):
    """(True, s) exited 0 - (False, s) exited non-zero - (None, s) did not complete; the log says why."""
    wrapper = gradle_wrapper(directory)
    env = dict(os.environ)
    sdk = android_sdk(directory)
    if sdk and not env.get("ANDROID_HOME"):
        env["ANDROID_HOME"] = str(sdk)
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        if wrapper is None:
            fh.write(f"\n{MARK} could not start Gradle: no gradlew in {directory}\n")
            return None, 0.0
        try:
            rc = subprocess.run([*_wrapper_cmd(wrapper), "--console=plain", task, *args], cwd=directory,
                                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\n{MARK} timed out after {timeout_s // 60} min\n")
            return None, round(time.monotonic() - start, 1)
        except OSError as e:
            fh.write(f"\n{MARK} could not start Gradle: {e}\n")
            return None, round(time.monotonic() - start, 1)
    return rc == 0, round(time.monotonic() - start, 1)


def _read(log: Path) -> str:
    try:
        return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def incomplete_reason(log: Path) -> str:
    for line in reversed(_read(log).splitlines()):
        if line.startswith(MARK):
            text = line[len(MARK):].strip()
            if text.startswith("timed out"):
                return f"{text} - Gradle may be waiting on a lock or a stuck daemon; see {log}"
            return text
    return f"Gradle did not complete; see {log}"


COMPILER_ERROR = re.compile(r"^e: (?:file://)?(.+?\.kts?):(\d+):(\d+):? (.+)$")
TEST_FAILURE = re.compile(r"^(\S+) > (.+) FAILED$")
TASK_MISSING = re.compile(r"Task '[^']+' not found in (root )?project|Cannot locate tasks? that match")
ENVIRONMENT_FAILURES = (
    (re.compile(r"SDK location not found"),
     "Android SDK not found by Gradle (it is needed to configure the build) - set ANDROID_HOME or sdk.dir in local.properties"),
    (re.compile(r"xcrun: error:"), "Xcode tools unavailable to Gradle (xcrun error) - check `xcode-select -p`"),
)


def failure_tail(log: Path, lines: int = 3) -> str:
    """First compiler error as File.kt:line:col message, else first failed test, else Gradle's summary."""
    text = [line for line in _read(log).splitlines() if line.strip()]
    for line in text:
        m = COMPILER_ERROR.match(line.strip())
        if m:
            path, row, col, msg = m.groups()
            return f"{Path(unquote(path)).name}:{row}:{col} {msg}"[:240]
    for line in text:
        m = TEST_FAILURE.match(line.strip())
        if m:
            return f"{m.group(1)} > {m.group(2)} FAILED"[:240]
    wrong = [i for i, line in enumerate(text) if "What went wrong" in line]
    pick = text[wrong[0] + 1: wrong[0] + 1 + lines] if wrong else text[-lines:]
    return " ".join(line.strip() for line in pick)[:240]


# -- scoping by what changed ------------------------------------------------------------------

BUILD_FILE = re.compile(r"(^|/)(settings\.gradle(\.kts)?|[^/]+\.gradle(\.kts)?|gradle\.properties|local\.properties"
                        r"|[^/]+\.versions\.toml|[^/]+\.def)$|^(gradle|build-logic|buildSrc)(/|$)")
SOURCE_SET = re.compile(r"(^|/)src/([^/]+)/")
NEUTRAL = re.compile(r"\.(md|txt|png|jpe?g|gif|svg|pdf|html|adoc|rst)$"
                     r"|^(docs|scripts|fastlane|\.github|\.gitlab|\.circleci|\.idea|\.vscode|\.fleet"
                     r"|\.claude|\.cursor|\.agents|\.codex)/"
                     r"|^\.gitlab-ci\.yml$|^\.git(ignore|attributes|modules)$|(^|/)(README|LICENSE|CHANGELOG|NOTICE)[^/]*$",
                     re.I)
IOS_NATIVE = re.compile(r"\.(swift|m|mm|h|plist|entitlements|storyboard|xib)$|^iosApp/"
                        r"|\.(xcodeproj|xcworkspace|xcconfig|xcassets)(/|$)|(^|/)Package\.(swift|resolved)$|(^|/)Podfile")
GRADLE_INPUT = ("build", "android", "ios", "shared")


def classify(path: str) -> str:
    """build | neutral | ios-native (Xcode only) | android | ios (Kotlin Apple source sets) | shared."""
    if BUILD_FILE.search(path):
        return "build"
    m = SOURCE_SET.search(path)
    if m and not path.startswith("iosApp/"):
        # Source sets first: resources, cinterop headers and bundled Swift under src/ are Gradle inputs.
        ss = m.group(2).lower()
        if ss.startswith("android") or ss in ("main", "test", "androidtest", "debug", "release"):
            return "android"
        if ss.startswith(("ios", "apple", "native", "darwin", "tvos", "watchos", "macos")):
            return "ios"
        return "shared"   # commonMain, commonTest, jvmMain and custom sets: assume both platforms
    if NEUTRAL.search(path):
        return "neutral"
    if IOS_NATIVE.search(path):
        return "ios-native"
    if path.endswith(("AndroidManifest.xml", ".pro")):
        return "android"
    return "shared"   # unknown -> assume it reaches both platforms


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def gradle_modules(directory: Path):
    """({module dir: Gradle path}, known). known=False when the layout cannot be read reliably."""
    for name in ("settings.gradle.kts", "settings.gradle"):
        f = directory / name
        if not f.is_file():
            continue
        text = _strip_comments(f.read_text(errors="replace"))
        if re.search(r"projectDir\s*=", text):
            return {}, False          # custom module directories: path != Gradle path
        paths = []
        for m in re.finditer(r"\binclude\s*\(([^)]*)\)", text):
            paths += re.findall(r"[\"']([^\"']+)[\"']", m.group(1))
        for m in re.finditer(r"(?m)^\s*include\s+([^\n(]+)$", text):
            paths += re.findall(r"[\"']([^\"']+)[\"']", m.group(1))
        if not paths or any("$" in p or "{" in p for p in paths):
            return {}, False
        return {p.lstrip(":").replace(":", "/"): ":" + p.lstrip(":") for p in paths}, True
    return {}, False


@dataclass
class Changes:
    base: str
    kinds: dict                  # path -> classify()
    modules: set                 # Gradle paths holding a Gradle-input change
    modules_known: bool = True   # False -> never narrow tests to modules

    @property
    def inputs(self) -> list:
        return [f for f, k in self.kinds.items() if k in GRADLE_INPUT]

    @property
    def build(self) -> bool:
        return any(k == "build" for k in self.kinds.values())

    @property
    def android_only(self) -> bool:
        return bool(self.inputs) and all(self.kinds[f] == "android" for f in self.inputs)

    @property
    def ios_only(self) -> bool:
        return bool(self.inputs) and all(self.kinds[f] == "ios" for f in self.inputs)

    @property
    def ios_kotlin(self) -> bool:
        return any(k == "ios" for k in self.kinds.values())

    def describe(self) -> str:
        counts = {}
        for k in self.kinds.values():
            counts[k] = counts.get(k, 0) + 1
        mix = ", ".join(f"{k} {n}" for k, n in sorted(counts.items())) or "none"
        mods = ", ".join(sorted(self.modules)) if self.modules_known else "unknown (tests not narrowed)"
        return f"{len(self.kinds)} changed file(s) since {self.base} ({mix}); modules: {mods or 'none'}"


def changes_since(directory: Path, branch=None, ref=None, remote: str = "origin", fetch: bool = True):
    """(Changes | None, notes). Everything differing from the merge-base: committed, uncommitted
    and untracked. None means "could not scope" - the caller then runs every check."""
    notes = []
    git = lambda *a: _run(["git", *a], cwd=directory)  # noqa: E731
    if ref is None:
        name = branch[len(remote) + 1:] if branch.startswith(remote + "/") else branch
        ref = f"{remote}/{name}"
        if fetch:
            try:
                fetched = subprocess.run(
                    ["git", "fetch", "--quiet", remote, f"+refs/heads/{name}:refs/remotes/{ref}"], cwd=directory,
                    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                fetched = False
            if not fetched:
                notes.append(f"could not fetch {ref}; scoping against the last fetched copy, which may be behind")
    if git("rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
        notes.append(f"{ref} not found - running every check, unscoped")
        return None, notes
    mb = git("merge-base", ref, "HEAD").stdout.strip()
    if not mb:
        notes.append(f"no merge-base between HEAD and {ref} - running every check, unscoped")
        return None, notes
    files = set(git("diff", "--name-only", "--relative", mb).stdout.splitlines())
    files |= set(git("ls-files", "--others", "--exclude-standard").stdout.splitlines())
    files.discard("")
    mods, known = gradle_modules(directory)
    kinds = {f: classify(f) for f in sorted(files)}
    touched = set()
    for f, k in kinds.items():
        if k not in GRADLE_INPUT or k == "build":
            continue
        owner = max((d for d in mods if f.startswith(d + "/")), key=len, default="")
        if owner:
            touched.add(mods[owner])
        else:
            known = False          # a source change outside every known module: do not narrow tests
    return Changes(base=ref, kinds=kinds, modules=touched, modules_known=known), notes


TEST_SETS = {"unit_test": ("commonTest", "androidUnitTest", "androidHostTest", "test", "jvmTest", "desktopTest"),
             "ios_test": ("commonTest", "iosTest", "iosSimulatorArm64Test", "iosX64Test", "appleTest", "nativeTest")}


def has_tests(directory: Path, module: str, kind: str) -> bool:
    src = directory / module.lstrip(":").replace(":", "/") / "src"
    return any((src / s).is_dir() for s in TEST_SETS[kind])


def link_to_compile(task: str):
    m = re.match(r"^(.*:)?link(?:Debug|Release)Framework(\w+)$", task)
    return f"{m.group(1) or ''}compileKotlin{m.group(2)}" if m else None


def scope(checks: list, changes) -> list:
    """Rewrite the plan to what this diff can affect. Skipped checks stay in the plan as
    NOT RUN with the reason, so the report accounts for every configured check."""
    if changes is None:
        return checks
    out = []
    for c in checks:
        c = replace(c)
        if c.not_run:
            pass
        elif not changes.inputs:
            only_xcode = any(k == "ios-native" for k in changes.kinds.values())
            c.not_run = ("only Swift / Xcode project files changed - no Gradle check builds them" if only_xcode
                         else "no build input changed (docs, CI or scripts only)")
        elif c.kind in IOS_KINDS and changes.android_only:
            c.not_run = "only Android code changed - iOS output unaffected"
        elif c.kind in ("android_build", "unit_test") and changes.ios_only:
            c.not_run = "only iOS Kotlin changed - Android and JVM output unaffected"
        elif c.kind == "common" and (changes.ios_only or changes.android_only):
            c.not_run = "only platform source sets changed - commonMain metadata unaffected"
        elif c.consumer:
            pass                   # consumers are never narrowed further
        elif c.kind == "ios_link" and not (changes.build or changes.ios_kotlin):
            compile_task = link_to_compile(c.task)
            if compile_task:
                c.task, c.kind = compile_task, "ios_compile"
                c.name += " (compile only: no build-file or iOS-source change)"
        elif c.kind in ("unit_test", "ios_test") and not changes.build and changes.modules_known:
            last = c.task.rsplit(":", 1)[-1]
            targets = [m for m in sorted(changes.modules) if has_tests(c.directory, m, c.kind)]
            if not targets:
                c.not_run = f"no changed module has {'JVM/Android' if c.kind == 'unit_test' else 'iOS'} tests"
            else:
                out += [replace(c, name=f"{c.name} - {m}", task=f"{m}:{last}", scoped=True) for m in targets]
                continue
        out.append(c)
    return out


# -- execution --------------------------------------------------------------------------------

def command_line(c: Check) -> str:
    return " ".join(["./gradlew", c.task, *c.args])


def _log_path(logs: Path, c: Check, suffix: str = "") -> Path:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{c.consumer or 'project'}-{c.task}").strip("_")
    return logs / f"{stem}{suffix}.log"


def execute(checks: list, dry_run: bool = False, only=None, logs: Path = Path("build/kmp-build-check/logs"),
            timeout_s: int = DEFAULT_TIMEOUT_MIN * 60, init_submodules: bool = False, changes=None) -> list:
    ios_cache, sub_cache, results = {}, {}, []

    def ios_reason(needs_sim: bool) -> str:
        if needs_sim not in ios_cache:
            ios_cache[needs_sim] = ios_unavailable_reason(needs_sim)
        return ios_cache[needs_sim]

    def submodules(d: Path) -> list:
        if d not in sub_cache:
            sub_cache[d] = uninitialised_submodules(d)
        return sub_cache[d]

    for c in scope(checks, changes):
        r = Result(c.name, c.platform, c.task, "NOT RUN", consumer=c.consumer, command=command_line(c))
        is_ios = c.platform == "ios" or c.kind in IOS_KINDS
        if only and c.platform not in (only, "any"):
            r.reason = f"filtered out by --only {only}"
        elif c.not_run:
            r.reason = c.not_run
        elif not c.directory.is_dir():
            r.reason = f"{c.consumer or 'project'} directory not found: {c.directory}"
        elif gradle_wrapper(c.directory) is None:
            r.reason = f"no Gradle wrapper (gradlew) in {c.directory}"
        elif dry_run:
            r.reason = f"dry run: would run {r.command}"
        elif is_ios and ios_reason(c.kind == "ios_test"):
            r.reason = ios_reason(c.kind == "ios_test")
        elif c.platform == "android" and android_sdk(c.directory) is None:
            r.reason = "Android SDK not configured - set ANDROID_HOME or sdk.dir in local.properties"
        elif submodules(c.directory) and not init_submodules:
            r.reason = (f"uninitialised git submodule(s): {', '.join(submodules(c.directory))} - "
                        f"run `git submodule update --init --recursive` or pass --init-submodules")
        else:
            if submodules(c.directory):
                root = git_root(c.directory)
                _run(["git", "submodule", "update", "--init", "--recursive"], cwd=root, timeout=600)
                sub_cache.pop(c.directory, None)
                if submodules(c.directory):
                    r.reason = "git submodules could not be initialised - check access to their remotes"
                    results.append(r)
                    continue
            _run_one(c, r, logs, timeout_s)
        results.append(r)
    return results


def _run_one(c: Check, r: Result, logs: Path, timeout_s: int) -> None:
    log = _log_path(logs, c)
    r.log = str(log)
    ok, secs = run_gradle(c.directory, c.task, c.args, log, timeout_s)
    r.seconds = secs
    if ok is None:
        r.reason = incomplete_reason(log)
        return
    if ok:
        r.state = "PASS"
        return
    text = _read(log)
    for pattern, reason in ENVIRONMENT_FAILURES:
        if pattern.search(text):
            r.reason = f"{reason}; see {log}"      # the machine, not the code: NOT RUN
            return
    if TASK_MISSING.search(text):
        if c.scoped:
            r.reason = f"{c.task} does not exist in this build"
            return
        r.state = "FAIL"
        r.reason = f"configured task not found - fix kmp-build-check.json or re-run --detect gradle ({failure_tail(log)})"
        return
    r.state, r.reason = "FAIL", failure_tail(log)
    if c.consumer and c.args:
        # Attribution: rebuild the consumer WITHOUT the substitution args. If that fails too,
        # the consumer was already broken and this change cannot be judged here.
        base_log = _log_path(logs, c, "-baseline")
        base_ok, base_secs = run_gradle(c.directory, c.task, [], base_log, timeout_s)
        r.seconds = round(r.seconds + base_secs, 1)
        if base_ok is None:
            r.state, r.reason = "NOT RUN", f"baseline re-check did not complete: {incomplete_reason(base_log)}"
        elif not base_ok:
            r.state = "NOT RUN"
            r.reason = (f"{c.consumer} already fails without the local library - a pre-existing breakage, "
                        f"not caused by this change ({failure_tail(base_log, 2)})")


def clean_worktree(directory: Path, into: Path) -> Path:
    """A throwaway git worktree of HEAD (committed code only). Returns the project dir inside it."""
    root = git_root(directory)
    if root is None:
        raise RuntimeError(f"{directory} is not inside a git repository")
    rel = directory.resolve().relative_to(root.resolve())
    into.mkdir(parents=True, exist_ok=True)
    wt = into / "worktree"
    subprocess.run(["git", "worktree", "add", "--detach", "--quiet", str(wt), "HEAD"], cwd=root, check=True,
                   capture_output=True)
    project = wt / rel
    props = directory / "local.properties"     # machine config, usually gitignored
    if props.is_file():
        (project / "local.properties").write_bytes(props.read_bytes())
    return project


def summary(results: list) -> dict:
    return {"pass": sum(r.state == "PASS" for r in results),
            "fail": sum(r.state == "FAIL" for r in results),
            "not_run": sum(r.state == "NOT RUN" for r in results)}


def render(results: list) -> str:
    if not results:
        return "no checks\n"
    width = max(len(r.name) for r in results) + 2
    out = []
    for r in results:
        detail = f"{r.seconds:>7.1f}s" if r.state != "NOT RUN" else ""
        line = f"{r.name:<{width}}{r.state:<9}{detail}"
        if r.reason:
            line += f"  - {r.reason}"
        out.append(line.rstrip())
    s = summary(results)
    out.append(f"\n{s['pass']} PASS, {s['fail']} FAIL, {s['not_run']} NOT RUN")
    return "\n".join(out)


# -- detection --------------------------------------------------------------------------------

TASK_LINE = re.compile(r"^([A-Za-z0-9_.\-]+(?::[A-Za-z0-9_.\-]+)*)(?: - .*)?$")


def parse_task_list(text: str) -> set:
    """Task paths from `./gradlew tasks --all` output, as :module:task."""
    tasks = set()
    for line in text.splitlines():
        m = TASK_LINE.match(line.rstrip())
        if m and re.match(r"[a-z]", m.group(1).rsplit(":", 1)[-1]):
            tasks.add(":" + m.group(1))
    return tasks


def gradle_task_list(project: Path, timeout_s: int):
    wrapper = gradle_wrapper(project)
    if wrapper is None:
        return None, f"no Gradle wrapper (gradlew) in {project}"
    try:
        p = subprocess.run([*_wrapper_cmd(wrapper), "--console=plain", "-q", "tasks", "--all"], cwd=project,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"`gradlew tasks --all` did not complete: {e}"
    if p.returncode != 0:
        tail = " ".join((p.stderr or p.stdout).strip().splitlines()[-3:])
        return None, f"`gradlew tasks --all` failed: {tail[:300]}"
    return parse_task_list(p.stdout), ""


def _qualified(module: str, task: str) -> str:
    return f":{task}" if module == ":" else f"{module}:{task}"


def detect_from_tasks(tasks: set):
    """(config, warnings) from the real task list. Unqualified task names run in every module
    that has them, so one check covers the whole build."""
    by_module = {}
    for t in tasks:
        mod, name = t.rsplit(":", 1)
        by_module.setdefault(mod or ":", set()).add(name)

    def anywhere(name):
        return sorted(m for m, names in by_module.items() if name in names)

    checks, warnings = [], []
    if anywhere("compileCommonMainKotlinMetadata"):
        checks.append({"name": "KMP common compile", "platform": "any", "task": "compileCommonMainKotlinMetadata"})
    else:
        warnings.append("no compileCommonMainKotlinMetadata task: is this a Kotlin Multiplatform build?")
    apps = sorted(m for m, names in by_module.items() if any(re.match(r"^install\w*Debug$", n) for n in names))
    for app in apps:
        names = by_module[app]
        flavoured = sorted(n for n in names if re.match(r"^assemble[A-Z]\w*Debug$", n) and "Test" not in n)
        task = flavoured[0] if flavoured else ("assembleDebug" if "assembleDebug" in names else None)
        if task:
            label = "Android assemble" if len(apps) == 1 else f"Android assemble ({app})"
            checks.append({"name": label, "platform": "android", "task": _qualified(app, task)})
            if flavoured:
                warnings.append(f"{app} has product flavours; picked {task} - edit the config to choose another")
    if not apps:
        if anywhere("assembleDebug"):
            checks.append({"name": "Android assemble (libraries)", "platform": "android", "task": "assembleDebug"})
        elif anywhere("compileAndroidMain"):
            checks.append({"name": "Android compile", "platform": "android", "task": "compileAndroidMain"})
    found_tests = False
    for name, label, plat in (("testAndroidHostTest", "Unit tests (Android host)", "android"),
                              ("testDebugUnitTest", "Unit tests (Android debug)", "android"),
                              ("jvmTest", "Unit tests (JVM)", "any"),
                              ("desktopTest", "Unit tests (desktop JVM)", "any")):
        if anywhere(name):
            checks.append({"name": label, "platform": plat, "task": name})
            found_tests = True
    if not found_tests:
        warnings.append("no JVM or Android host unit-test task found (with the Android KMP library plugin, "
                        "host tests exist only after withHostTest {} is configured)")
    for target in ("IosSimulatorArm64", "IosX64", "IosArm64"):
        if anywhere(f"linkDebugFramework{target}"):
            checks.append({"name": "iOS framework link", "platform": "ios", "task": f"linkDebugFramework{target}"})
            break
    else:
        if anywhere("compileKotlinIosSimulatorArm64"):
            checks.append({"name": "iOS compile", "platform": "ios", "task": "compileKotlinIosSimulatorArm64"})
            warnings.append("no debug framework binary declared; the iOS check compiles but does not link")
        else:
            warnings.append("no iOS target found: nothing will check iosMain")
    if anywhere("iosSimulatorArm64Test"):
        checks.append({"name": "iOS simulator tests", "platform": "ios", "task": "iosSimulatorArm64Test"})
    elif anywhere("iosX64Test"):
        checks.append({"name": "iOS simulator tests", "platform": "ios", "task": "iosX64Test"})
    return {"version": 1, "checks": checks, "consumers": []}, warnings


def _module_build_file(directory: Path):
    return next((directory / n for n in ("build.gradle.kts", "build.gradle") if (directory / n).is_file()), None)


def detect_static(project: Path):
    """(config, warnings) from reading build files only. Fast and offline, but blind to
    convention plugins, variants and plugin-created task names."""
    warnings = []
    mods, known = gradle_modules(project)
    if not known:
        warnings.append("could not read the module list from settings.gradle(.kts); only the root build file was read")
    module_dirs = {":": project, **{path: project / d for d, path in mods.items()}}
    info = {}
    for path, d in module_dirs.items():
        bf = _module_build_file(d)
        if bf is None:
            continue
        t = _strip_comments(bf.read_text(errors="replace"))
        # Root build files declare plugins with `apply false` for the modules; those lines apply nothing here.
        t = re.sub(r"(?m)^.*\bapply\s*\(?\s*false\s*\)?.*$", "", t)
        jvm = re.findall(r"\bjvm\s*\(\s*(?:\"(\w+)\")?", t)
        info[path] = {
            "kmp": bool(re.search(r"multiplatform", t, re.I)),
            "app": bool(re.search(r"android[._-]?application", t, re.I)),
            "kmp_android_lib": bool(re.search(r"android[._-]?(kotlin[._-]?)?multiplatform[._-]?library", t, re.I)),
            "android_lib": bool(re.search(r"android[._-]?library|androidTarget\s*[({]", t, re.I)),
            "host_tests": bool(re.search(r"withHostTest(Builder)?\b", t)),
            "flavours": "productFlavors" in t,
            "ios_sim": bool(re.search(r"iosSimulatorArm64\s*\(", t)),
            "ios_x64": bool(re.search(r"iosX64\s*\(", t)),
            "ios_any": bool(re.search(r"\bios(SimulatorArm64|X64|Arm64)\s*\(", t)),
            "framework": bool(re.search(r"binaries\s*\.\s*framework|\bframework\s*\{|XCFramework\s*\(", t)),
            "cocoapods": bool(re.search(r"\bcocoapods\s*\{", t)),
            "jvm": sorted({(n or "jvm") for n in jvm}),
            "opaque": bool(re.search(r"\bid\s*\(\s*\"(?!com\.android|org\.jetbrains)", t)),
        }
    checks = []
    if any(i["kmp"] for i in info.values()):
        checks.append({"name": "KMP common compile", "platform": "any", "task": "compileCommonMainKotlinMetadata"})
    apps = sorted(p for p, i in info.items() if i["app"])
    for app in apps:
        label = "Android assemble" if len(apps) == 1 else f"Android assemble ({app})"
        checks.append({"name": label, "platform": "android", "task": _qualified(app, "assembleDebug")})
        if info[app]["flavours"]:
            warnings.append(f"{app} declares productFlavors: assembleDebug builds every flavour - "
                            f"replace it with one assemble<Flavour>Debug task")
    if not apps:
        if any(i["android_lib"] and not i["kmp_android_lib"] for i in info.values()):
            checks.append({"name": "Android assemble (libraries)", "platform": "android", "task": "assembleDebug"})
        elif any(i["kmp_android_lib"] for i in info.values()):
            checks.append({"name": "Android compile", "platform": "android", "task": "compileAndroidMain"})
    if any(i["kmp_android_lib"] and i["host_tests"] for i in info.values()):
        checks.append({"name": "Unit tests (Android host)", "platform": "android", "task": "testAndroidHostTest"})
    for p, i in sorted(info.items()):
        if i["kmp_android_lib"] and not i["host_tests"]:
            warnings.append(f"{p} uses the Android KMP library plugin without withHostTest {{}}: "
                            f"its commonTest never runs on the Android side")
    # Flavoured apps have test<Flavour>DebugUnitTest, not testDebugUnitTest.
    if any(i["android_lib"] and not i["kmp_android_lib"] and not (i["app"] and i["flavours"]) for i in info.values()):
        checks.append({"name": "Unit tests (Android debug)", "platform": "android", "task": "testDebugUnitTest"})
    for name in sorted({n for i in info.values() for n in i["jvm"]}):
        checks.append({"name": f"Unit tests ({name})", "platform": "any", "task": f"{name}Test"})
    framework_mods = [p for p, i in info.items() if i["ios_any"] and i["framework"]]
    if framework_mods:
        target = "IosSimulatorArm64" if any(info[p]["ios_sim"] for p in framework_mods) else (
            "IosX64" if any(info[p]["ios_x64"] for p in framework_mods) else "IosArm64")
        checks.append({"name": "iOS framework link", "platform": "ios", "task": f"linkDebugFramework{target}"})
    elif any(i["ios_sim"] for i in info.values()):
        checks.append({"name": "iOS compile", "platform": "ios", "task": "compileKotlinIosSimulatorArm64"})
    if any(i["ios_sim"] for i in info.values()):
        checks.append({"name": "iOS simulator tests", "platform": "ios", "task": "iosSimulatorArm64Test"})
    elif any(i["ios_x64"] for i in info.values()):
        checks.append({"name": "iOS simulator tests", "platform": "ios", "task": "iosX64Test"})
    for p, i in sorted(info.items()):
        if i["cocoapods"]:
            warnings.append(f"{p} uses the CocoaPods plugin: its framework link task has a different name - "
                            f"use --detect gradle")
        if i["opaque"] and p != ":" and not any(i[k] for k in ("kmp", "app", "android_lib", "kmp_android_lib")):
            warnings.append(f"{p} applies plugins this reader cannot see into (convention plugins?) - "
                            f"use --detect gradle")
    if not any(c["platform"] == "ios" for c in checks):
        warnings.append("no iOS target found in any build file: nothing will check iosMain")
    warnings.append("static detection guesses from build files; confirm each task with "
                    "`./gradlew <module>:tasks --all` or use --detect gradle before trusting a FAIL")
    return {"version": 1, "checks": checks, "consumers": []}, warnings


# -- CLI --------------------------------------------------------------------------------------

def _detect(a, project: Path, config_path: Path) -> int:
    if a.detect == "gradle":
        tasks, err = gradle_task_list(project, a.timeout_minutes * 60)
        if tasks is None:
            print(err, file=sys.stderr)
            return 2
        cfg, warnings = detect_from_tasks(tasks)
    else:
        cfg, warnings = detect_static(project)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    text = json.dumps(cfg, indent=2) + "\n"
    if a.write:
        if config_path.exists() and not a.force:
            print(f"{config_path} exists - pass --force to overwrite it", file=sys.stderr)
            return 2
        config_path.write_text(text, encoding="utf-8")
        print(f"wrote {config_path} ({len(cfg['checks'])} checks)", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_checks.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, default=Path.cwd(), help="Gradle root holding gradlew (default: cwd)")
    ap.add_argument("--config", type=Path, help=f"config file (default: <project>/{CONFIG_NAME})")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; run nothing")
    ap.add_argument("--only", choices=["android", "ios"], help="one platform's checks (plus platform 'any')")
    scope_group = ap.add_mutually_exclusive_group()
    scope_group.add_argument("--base", metavar="BRANCH",
                             help="scope to the diff vs <remote>/BRANCH (fetched first; a local branch is never used)")
    scope_group.add_argument("--base-ref", metavar="REF", help="scope to the diff vs this exact git ref (no fetch)")
    ap.add_argument("--remote", default="origin", help="remote for --base (default: origin)")
    ap.add_argument("--no-fetch", action="store_true", help="with --base, do not git fetch first")
    ap.add_argument("--json", metavar="PATH", help="write results as JSON to PATH ('-' = stdout, table goes to stderr)")
    ap.add_argument("--logs", type=Path, help="Gradle log directory (default: <project>/build/kmp-build-check/logs)")
    ap.add_argument("--clean", action="store_true",
                    help="build a temporary git worktree of HEAD: committed code only, untracked files excluded")
    ap.add_argument("--init-submodules", action="store_true", help="run git submodule update --init when needed")
    ap.add_argument("--no-consumers", action="store_true", help="skip the consumer checks")
    ap.add_argument("--timeout-minutes", type=int, default=DEFAULT_TIMEOUT_MIN, help="per Gradle run (default: 45)")
    ap.add_argument("--validate", action="store_true", help="validate the config and exit")
    ap.add_argument("--detect", choices=["static", "gradle"], help="propose a config instead of running checks")
    ap.add_argument("--write", action="store_true", help="with --detect, save the proposal to the config path")
    ap.add_argument("--force", action="store_true", help="with --detect --write, overwrite an existing config")
    a = ap.parse_args(argv)
    # These values reach git as positional arguments; a leading '-' would be read as an option.
    for flag, value in (("--remote", a.remote), ("--base", a.base), ("--base-ref", a.base_ref)):
        if value and value.startswith("-"):
            ap.error(f"{flag} must not start with '-': {value!r}")

    project = a.project.resolve()
    config_path = (a.config or project / CONFIG_NAME).resolve()
    if a.detect:
        return _detect(a, project, config_path)
    cfg, errors = load_config(config_path)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    if a.validate:
        print(f"{config_path}: valid ({len(cfg['checks'])} checks, {len(cfg.get('consumers', []))} consumers)")
        return 0

    notes = []
    changes = None
    if a.base or a.base_ref:
        changes, notes = changes_since(project, branch=a.base, ref=a.base_ref, remote=a.remote, fetch=not a.no_fetch)
    stray = [] if a.clean else untracked_sources(project)
    if stray:
        shown = ", ".join(stray[:3]) + (f" (+{len(stray) - 3} more)" if len(stray) > 3 else "")
        notes.append(f"{len(stray)} untracked source file(s): {shown}. The build includes them, so it can PASS "
                     f"while the committed code is broken - commit them or re-run with --clean")

    logs = (a.logs or project / "build" / "kmp-build-check" / "logs").resolve()
    tmp = None
    run_project = project
    try:
        if a.clean:
            tmp = Path(tempfile.mkdtemp(prefix="kmp-build-check-"))
            run_project = clean_worktree(project, tmp)
        checks = build_checks(cfg, project, include_consumers=not a.no_consumers)
        for c in checks:
            if c.consumer and a.clean:
                c.not_run = "consumers build against the working copy, not the --clean worktree - re-run without --clean"
            elif not c.consumer:
                c.directory = run_project
        results = execute(checks, dry_run=a.dry_run, only=a.only, logs=logs, timeout_s=a.timeout_minutes * 60,
                          init_submodules=a.init_submodules, changes=changes)
    finally:
        if tmp is not None:
            root = git_root(project)
            if root is not None:
                _run(["git", "worktree", "remove", "--force", str(tmp / "worktree")], cwd=root)
            shutil.rmtree(tmp, ignore_errors=True)

    table_out = sys.stderr if a.json == "-" else sys.stdout
    for n in notes:
        print(f"WARNING: {n}", file=sys.stderr)
    if changes is not None:
        print(f"Scoped to the diff: {changes.describe()}\n", file=table_out)
    print(render(results), file=table_out)
    if a.json:
        doc = {"tool": "kmp-build-check", "project": str(project), "dry_run": a.dry_run,
               "scope": changes.describe() if changes is not None else None, "warnings": notes,
               "summary": summary(results), "results": [asdict(r) for r in results]}
        text = json.dumps(doc, indent=2) + "\n"
        if a.json == "-":
            sys.stdout.write(text)
        else:
            Path(a.json).write_text(text, encoding="utf-8")
    return 1 if any(r.state == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
