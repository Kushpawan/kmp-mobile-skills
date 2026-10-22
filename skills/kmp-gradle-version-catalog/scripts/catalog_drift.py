#!/usr/bin/env python3
"""Compare Gradle version catalogs (libs.versions.toml) and report drift. Read-only.

Usage:
    python3 scripts/catalog_drift.py CATALOG [CATALOG ...] [options]

Each CATALOG is a path to a TOML version catalog, optionally prefixed with a label:
    app=../app/gradle/libs.versions.toml  sdk=../sdk/gradle/libs.versions.toml

Report sections:
    versions   [versions] keys whose values differ between catalogs or are missing from some
    libraries  [libraries] aliases whose module or resolved version differs or is missing
    plugins    [plugins] aliases whose id or resolved version differs or is missing
    inline     library/plugin entries with a literal version instead of version.ref (info only)
    hardcoded  versioned coordinates or plugin versions in build scripts (with --scan-gradle)

Exit codes:
    0  no drift, or drift found without --fail-on-drift
    1  drift or hardcoded versions found and --fail-on-drift was given
    2  usage error, unreadable file or invalid TOML

Requires Python 3.11+ (tomllib). Standard library only. Never modifies files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on old interpreters
    tomllib = None

SKIP_DIRS = {"build", ".gradle", ".git", "node_modules", ".idea", ".kotlin"}
COORDINATE_RE = re.compile(r"""["']([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([0-9][^"'\s]*)["']""")
PLUGIN_VERSION_RE = re.compile(
    r"""(?:id\s*\(\s*["']([^"']+)["']\s*\)|kotlin\s*\(\s*["']([^"']+)["']\s*\))\s*version\s*["']([^"']+)["']"""
)


def parse_catalog_args(raw_args: list[str]) -> list[tuple[str, str]]:
    """Return (label, path) pairs. `label=path` sets a label; otherwise the path is the label."""
    pairs: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for raw in raw_args:
        label, sep, path = raw.partition("=")
        if not sep or "/" in label or "\\" in label or not label:
            label, path = raw, raw
        count = seen.get(label, 0)
        seen[label] = count + 1
        pairs.append((label if count == 0 else f"{label}#{count + 1}", path))
    return pairs


def load_catalog(path: str) -> dict:
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def normalize_version(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return ", ".join(f"{key}={value[key]}" for key in sorted(value))
    return str(value)


def resolve_version(entry: dict, versions: dict) -> tuple[str | None, bool]:
    """Return (resolved version, is_inline) for a library or plugin table entry."""
    version = entry.get("version")
    if isinstance(version, dict) and "ref" in version:
        ref = version["ref"]
        if ref not in versions:
            return f"<missing version.ref '{ref}'>", False
        return normalize_version(versions[ref]), False
    if version is None:
        return None, False
    return normalize_version(version), True


def resolve_library(entry, versions: dict) -> tuple[str, str | None, bool]:
    if isinstance(entry, str):
        parts = entry.split(":")
        module = ":".join(parts[:2])
        version = parts[2] if len(parts) > 2 else None
        return module, version, version is not None
    module = entry.get("module") or f"{entry.get('group', '?')}:{entry.get('name', '?')}"
    version, inline = resolve_version(entry, versions)
    return module, version, inline


def resolve_plugin(entry, versions: dict) -> tuple[str, str | None, bool]:
    if isinstance(entry, str):
        plugin_id, _, version = entry.partition(":")
        return plugin_id, version or None, bool(version)
    version, inline = resolve_version(entry, versions)
    return entry.get("id", "?"), version, inline


def describe(catalog: dict) -> dict:
    """Flatten one catalog into {'versions': {k: v}, 'libraries': {...}, 'plugins': {...}, 'inline': [...]}."""
    versions = catalog.get("versions", {})
    result = {"versions": {k: normalize_version(v) for k, v in versions.items()},
              "libraries": {}, "plugins": {}, "inline": []}
    for section, resolver in (("libraries", resolve_library), ("plugins", resolve_plugin)):
        for alias, entry in catalog.get(section, {}).items():
            name, version, inline = resolver(entry, versions)
            result[section][alias] = name if version is None else f"{name}:{version}"
            if inline:
                result["inline"].append({"section": section, "alias": alias, "version": version})
    return result


def compare(described: dict[str, dict], section: str, only_differs: bool) -> list[dict]:
    labels = list(described)
    keys = sorted(set().union(*(described[label][section].keys() for label in labels)))
    drift = []
    for key in keys:
        values = {label: described[label][section].get(key) for label in labels}
        present = {value for value in values.values() if value is not None}
        missing = any(value is None for value in values.values())
        differs = len(present) > 1
        if differs or (missing and not only_differs and len(labels) > 1):
            status = "differs" if differs and not missing else "missing" if not differs else "differs+missing"
            drift.append({"key": key, "status": status, "values": values})
    return drift


def scan_gradle(roots: list[str]) -> list[dict]:
    hits = []
    for root in roots:
        for directory, subdirs, files in os.walk(root):
            subdirs[:] = sorted(d for d in subdirs if d not in SKIP_DIRS)
            for name in sorted(files):
                if not (name.endswith(".gradle.kts") or name.endswith(".gradle")):
                    continue
                path = os.path.join(directory, name)
                with open(path, encoding="utf-8", errors="replace") as handle:
                    for number, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if stripped.startswith("//") or stripped.startswith("*"):
                            continue
                        for match in COORDINATE_RE.finditer(line):
                            hits.append({"file": path, "line": number, "kind": "coordinate",
                                         "text": match.group(0).strip("\"'")})
                        for match in PLUGIN_VERSION_RE.finditer(line):
                            plugin_id = match.group(1) or f"kotlin({match.group(2)})"
                            hits.append({"file": path, "line": number, "kind": "plugin",
                                         "text": f"{plugin_id} version {match.group(3)}"})
    return hits


def build_report(catalog_args: list[str], scan_roots: list[str], only_differs: bool) -> dict:
    pairs = parse_catalog_args(catalog_args)
    described = {}
    for label, path in pairs:
        described[label] = describe(load_catalog(path))
    drift = {section: compare(described, section, only_differs)
             for section in ("versions", "libraries", "plugins")}
    inline = [dict(item, catalog=label) for label, info in described.items() for item in info["inline"]]
    hardcoded = scan_gradle(scan_roots) if scan_roots else []
    summary = {f"{section}_drift": len(items) for section, items in drift.items()}
    summary.update({"inline": len(inline), "hardcoded": len(hardcoded)})
    return {"catalogs": [{"label": label, "path": path} for label, path in pairs],
            "drift": drift, "inline": inline, "hardcoded": hardcoded, "summary": summary}


def render_table(report: dict) -> str:
    lines = ["catalogs: " + ", ".join(f"{c['label']} ({c['path']})" for c in report["catalogs"])]
    for section, items in report["drift"].items():
        lines.append(f"\n[{section}] {len(items)} drift")
        for item in items:
            values = "  ".join(f"{label}={value if value is not None else '-'}"
                               for label, value in item["values"].items())
            lines.append(f"  {item['status']:<16} {item['key']:<40} {values}")
    lines.append(f"\n[inline] {len(report['inline'])} entries with a literal version")
    for item in report["inline"]:
        lines.append(f"  {item['catalog']}: {item['section']}.{item['alias']} = {item['version']}")
    if report["hardcoded"]:
        lines.append(f"\n[hardcoded] {len(report['hardcoded'])} versions in build scripts")
        for hit in report["hardcoded"]:
            lines.append(f"  {hit['file']}:{hit['line']}  {hit['kind']}  {hit['text']}")
    lines.append("\nsummary: " + ", ".join(f"{k}={v}" for k, v in report["summary"].items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("catalogs", nargs="+", metavar="CATALOG", help="[label=]path/to/libs.versions.toml")
    parser.add_argument("--format", choices=("table", "json"), default="table", help="output format (default: table)")
    parser.add_argument("--scan-gradle", action="append", default=[], metavar="DIR",
                        help="also scan *.gradle(.kts) under DIR for hardcoded versions; repeatable")
    parser.add_argument("--only-differs", action="store_true",
                        help="ignore keys that are merely missing from some catalogs")
    parser.add_argument("--fail-on-drift", action="store_true",
                        help="exit 1 when drift or hardcoded versions are found")
    args = parser.parse_args(argv)

    if tomllib is None:
        print("error: Python 3.11+ is required (tomllib)", file=sys.stderr)
        return 2
    try:
        report = build_report(args.catalogs, args.scan_gradle, args.only_differs)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2) if args.format == "json" else render_table(report))
    found = any(report["drift"].values()) or bool(report["hardcoded"])
    return 1 if (found and args.fail_on_drift) else 0


if __name__ == "__main__":
    sys.exit(main())
