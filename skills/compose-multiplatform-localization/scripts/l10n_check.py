#!/usr/bin/env python3
"""Check and pseudo-localise Compose Multiplatform string resources.

Works on a `composeResources` directory (for example
`shared/src/commonMain/composeResources`). Standard library only. No network.

Subcommands
  check   Report missing keys, keys absent from the default `values/`,
          placeholder mismatches, placeholders Compose Multiplatform does not
          substitute, plurals without `other`, and string-array size mismatches.
  pseudo  Write `values-en-rXA/strings.xml`: accented, expanded, bracketed copies
          of the default strings with placeholders and escapes preserved.

Output is JSON on stdout (or a fixed-width table with --format table).
Exit codes: 0 ok, 1 findings at error level (or warnings with --strict), 2 usage/IO error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Compose Multiplatform substitutes only positional %N$s / %N$d (both mean "string").
SUPPORTED_PLACEHOLDER = re.compile(r"%(\d+)\$[sd]")
# Anything that looks like a printf conversion. A space is deliberately not a flag,
# so literal text such as "50% off" is not reported.
FORMAT_LIKE = re.compile(r"%(?:\d+\$)?[-#+0,(]*\d*(?:\.\d+)?[a-zA-Z@]")
# Segments the pseudo-localiser must keep verbatim.
PROTECTED = re.compile(r"(%\d+\$[sd]|\\u[0-9a-fA-F]{4}|\\.)")

ACCENTS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "àƀçđéƒĝĥîĵķļɱñöþʠŕšţûṽŵẋýžÀßÇĐÉƑĜĤÎĴĶĻṀÑÖÞǪŔŠŢÛṼŴẊÝŽ",
)
PSEUDO_DIR = "values-en-rXA"


@dataclass
class LocaleStrings:
    strings: dict[str, str] = field(default_factory=dict)
    plurals: dict[str, dict[str, str]] = field(default_factory=dict)
    arrays: dict[str, list[str]] = field(default_factory=dict)
    untranslatable: set[str] = field(default_factory=set)


@dataclass
class Finding:
    severity: str  # "error" | "warning"
    code: str
    locale: str
    key: str
    message: str


def text_of(element: ET.Element) -> str:
    return "".join(element.itertext())


def load_locale(directory: Path, findings: list[Finding]) -> LocaleStrings:
    result = LocaleStrings()
    locale = directory.name
    for xml_file in sorted(directory.glob("*.xml")):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError as error:
            findings.append(Finding("error", "xml-parse-error", locale, xml_file.name, str(error)))
            continue
        for element in root:
            name = element.get("name")
            if not name:
                continue
            seen = name in result.strings or name in result.plurals or name in result.arrays
            if seen:
                findings.append(Finding("error", "duplicate-key", locale, name, f"defined again in {xml_file.name}"))
            if element.get("translatable") == "false":
                result.untranslatable.add(name)
            if element.tag == "string":
                result.strings[name] = text_of(element)
            elif element.tag == "plurals":
                result.plurals[name] = {item.get("quantity", ""): text_of(item) for item in element.findall("item")}
            elif element.tag == "string-array":
                result.arrays[name] = [text_of(item) for item in element.findall("item")]
    return result


def find_locale_dirs(resources: Path) -> dict[str, Path]:
    return {d.name: d for d in sorted(resources.iterdir()) if d.is_dir() and (d.name == "values" or d.name.startswith("values-"))}


def placeholder_indices(text: str) -> list[str]:
    return sorted(SUPPORTED_PLACEHOLDER.findall(text))


def unsupported_placeholders(text: str) -> list[str]:
    return [m.group(0) for m in FORMAT_LIKE.finditer(text) if not SUPPORTED_PLACEHOLDER.fullmatch(m.group(0))]


def all_texts(data: LocaleStrings) -> list[tuple[str, str]]:
    pairs = list(data.strings.items())
    pairs += [(f"{k}[{q}]", v) for k, items in data.plurals.items() for q, v in items.items()]
    pairs += [(f"{k}[{i}]", v) for k, items in data.arrays.items() for i, v in enumerate(items)]
    return pairs


def check(resources: Path) -> list[Finding]:
    findings: list[Finding] = []
    dirs = find_locale_dirs(resources)
    if "values" not in dirs:
        return [Finding("error", "missing-default-dir", "values", "-", "no default values/ directory")]
    locales = {name: load_locale(path, findings) for name, path in dirs.items()}
    default = locales["values"]

    for name, data in locales.items():
        for key, text in all_texts(data):
            for token in unsupported_placeholders(text):
                findings.append(Finding("error", "unsupported-placeholder", name, key,
                                        f"'{token}' is not substituted; use %1$s / %1$d"))
        for key, items in data.plurals.items():
            if "other" not in items:
                findings.append(Finding("error", "plural-missing-other", name, key, "plurals need an 'other' item"))
        if name == "values":
            continue
        for key in sorted(set(data.strings) - set(default.strings)) + sorted(set(data.plurals) - set(default.plurals)) + sorted(set(data.arrays) - set(default.arrays)):
            findings.append(Finding("error", "missing-default", name, key, "key exists here but not in values/; lookups fail for other locales"))
        for key, text in default.strings.items():
            if key in default.untranslatable:
                continue
            if key not in data.strings:
                findings.append(Finding("warning", "missing-translation", name, key, "falls back to the default language"))
            elif placeholder_indices(text) != placeholder_indices(data.strings[key]):
                findings.append(Finding("error", "placeholder-mismatch", name, key,
                                        f"default {placeholder_indices(text)} vs {placeholder_indices(data.strings[key])}"))
        for key in default.plurals:
            if key not in data.plurals and key not in default.untranslatable:
                findings.append(Finding("warning", "missing-translation", name, key, "plural falls back to the default language"))
        for key, items in default.arrays.items():
            if key in data.arrays and len(data.arrays[key]) != len(items):
                findings.append(Finding("warning", "array-size-mismatch", name, key,
                                        f"default has {len(items)} items, this locale {len(data.arrays[key])}"))
            elif key not in data.arrays and key not in default.untranslatable:
                findings.append(Finding("warning", "missing-translation", name, key, "array falls back to the default language"))
    return findings


def pseudo_text(text: str, expand: float) -> str:
    parts = PROTECTED.split(text)
    visible = "".join(p.translate(ACCENTS) if i % 2 == 0 else p for i, p in enumerate(parts))
    letters = sum(len(p) for i, p in enumerate(parts) if i % 2 == 0)
    padding = "·" * max(1, round(letters * expand)) if letters else ""
    return f"[{visible}{' ' + padding if padding else ''}]"


def pseudo(resources: Path, expand: float, dry_run: bool) -> dict:
    findings: list[Finding] = []
    default_dir = resources / "values"
    if not default_dir.is_dir():
        raise FileNotFoundError(f"{default_dir} not found")
    default = load_locale(default_dir, findings)
    root = ET.Element("resources")
    for key, text in default.strings.items():
        if key in default.untranslatable:
            continue
        ET.SubElement(root, "string", name=key).text = pseudo_text(text, expand)
    for key, items in default.plurals.items():
        plural = ET.SubElement(root, "plurals", name=key)
        for quantity, text in items.items():
            ET.SubElement(plural, "item", quantity=quantity).text = pseudo_text(text, expand)
    for key, items in default.arrays.items():
        array = ET.SubElement(root, "string-array", name=key)
        for text in items:
            ET.SubElement(array, "item").text = pseudo_text(text, expand)
    target = resources / PSEUDO_DIR / "strings.xml"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(root)
        ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return {
        "target": str(target),
        "dry_run": dry_run,
        "strings": len(root.findall("string")),
        "plurals": len(root.findall("plurals")),
        "arrays": len(root.findall("string-array")),
        "parse_errors": [asdict(f) for f in findings],
    }


def print_table(findings: list[Finding]) -> None:
    print(f"{'SEVERITY':<8} {'CODE':<24} {'LOCALE':<16} {'KEY':<32} MESSAGE")
    for f in findings:
        print(f"{f.severity:<8} {f.code:<24} {f.locale:<16} {f.key:<32} {f.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="report localisation problems")
    check_parser.add_argument("resources", type=Path, help="path to a composeResources directory")
    check_parser.add_argument("--format", choices=["json", "table"], default="json")
    check_parser.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    pseudo_parser = sub.add_parser("pseudo", help=f"write {PSEUDO_DIR}/strings.xml")
    pseudo_parser.add_argument("resources", type=Path, help="path to a composeResources directory")
    pseudo_parser.add_argument("--expand", type=float, default=0.4, help="padding ratio (default 0.4)")
    pseudo_parser.add_argument("--dry-run", action="store_true", help="report what would be written; write nothing")
    args = parser.parse_args(argv)

    if not args.resources.is_dir():
        print(json.dumps({"error": f"{args.resources} is not a directory"}))
        return 2
    if args.command == "pseudo":
        try:
            print(json.dumps(pseudo(args.resources, args.expand, args.dry_run), ensure_ascii=False, indent=2))
        except FileNotFoundError as error:
            print(json.dumps({"error": str(error)}))
            return 2
        return 0

    findings = check(args.resources)
    errors = sum(f.severity == "error" for f in findings)
    warnings = sum(f.severity == "warning" for f in findings)
    if args.format == "table":
        print_table(findings)
    else:
        print(json.dumps({"errors": errors, "warnings": warnings, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
