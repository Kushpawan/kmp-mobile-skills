# Findings schema

One JSON object per line (JSON Lines), one line per finding, emitted before the human report.
Prose cannot be counted, merged across reviewers or tracked over time; these lines can. The same
schema is used by `mobile-security-review`, `mobile-platform-parity` and the `kotlin-reviewer` /
`swift-reviewer` agents, so their output merges without translation.

## Fields

| Field | Type | Required | Values |
|---|---|---|---|
| `file` | string | yes | Path relative to the repository root |
| `line` | integer | yes | 1-based line of the defect in the current working tree; `0` for a whole-file finding |
| `severity` | string | yes | `Critical` · `High` · `Medium` · `Low` — never below the lens row's floor |
| `tier` | integer | yes | `1` = enforces a rule written in the project's files · `2` = a known defect class from a lens table |
| `lens` | string | yes | Lens key, see below |
| `title` | string | yes | One line, under ~80 characters, states the defect |
| `why` | string | yes | The concrete failure: which input or state leads to which wrong behaviour. Not "could be improved" |
| `fix` | string | yes | The specific change. Not "consider refactoring" |
| `rule` | string | yes | Tier 1: the rule file and section, e.g. `CONTRIBUTING.md §Error handling`. Tier 2: the defect class name |
| `verdict` | string | yes | `CONFIRMED` = re-read and the failure holds · `PLAUSIBLE` = first read only. Every Critical and High must be `CONFIRMED` |
| `masvs` | string | no | Security findings: the OWASP MASVS v2 control, e.g. `MASVS-STORAGE-2` |
| `counterpart` | string | no | Parity findings: `file:line` of the other platform's code |

Do not add other fields; consumers may reject unknown keys.

## Lens keys

`<prefix>/<lensName>`, where `lensName` is the row's **Lens** cell with punctuation and backticks
removed, in lowerCamelCase.

| Prefix | Source |
|---|---|
| `kotlin` | `lens-kotlin-compose.md` |
| `swift` | `lens-swift-ios.md` |
| `build` | `lens-build-ci.md` |
| `security` | `mobile-security-review` lens |
| `parity` | `mobile-platform-parity` dimensions |
| `project` | A Tier 1 rule: `project/<rule-file-stem>`, e.g. `project/contributing` |
| `unlisted` | A real concern no row covers. Always Tier 2 |

Examples: the Lens cell `` `GlobalScope` `` becomes `kotlin/globalScope`; "Swallowed cancellation"
becomes `kotlin/swallowedCancellation`; "Checked continuation misuse" becomes
`swift/checkedContinuationMisuse`.

Keep keys stable. Teams that track which lenses get rejected group by this key — renaming a Lens
cell breaks that history.

## Examples

```json
{"file":"shared/src/commonMain/kotlin/com/example/app/notes/NotesSync.kt","line":88,"severity":"Critical","tier":2,"lens":"kotlin/swallowedCancellation","title":"Cancellation swallowed in the sync loop","why":"catch (e: Exception) around syncPage() also catches CancellationException; after logout cancels the scope the loop keeps calling the API with a cleared token","fix":"rethrow CancellationException before the generic catch, or catch IOException only","rule":"Swallowed cancellation","verdict":"CONFIRMED"}
{"file":"iosApp/iosApp/Notes/NoteEditorView.swift","line":42,"severity":"High","tier":1,"lens":"project/contributing","title":"Save button has no accessibility identifier","why":"the UI test suite locates controls by identifier; this one is found by label text and breaks on every copy change","fix":"add .accessibilityIdentifier(\"noteEditor.saveButton\") from the screen's identifier namespace","rule":"CONTRIBUTING.md §UI tests","verdict":"CONFIRMED"}
{"file":"composeApp/src/androidMain/AndroidManifest.xml","line":31,"severity":"High","tier":2,"lens":"security/exportedComponent","title":"Share receiver exported without a permission","why":"any installed app can send the intent and trigger an upload of the attached URI","fix":"set android:exported=\"false\", or protect it with a signature permission","rule":"Exported component","masvs":"MASVS-PLATFORM-1","verdict":"CONFIRMED"}
```

## Summary line

After the JSON lines, one line: `reviewed: <n> files · <m> findings`. With no findings, this line
alone is the complete machine output.

## Checking the output

```bash
# Prints any line with a disallowed severity or verdict, or an unconfirmed Critical/High
jq -c 'select((.severity|IN("Critical","High","Medium","Low")|not)
              or (.verdict|IN("CONFIRMED","PLAUSIBLE")|not)
              or ((.severity=="Critical" or .severity=="High") and .verdict!="CONFIRMED"))' findings.jsonl
```

Empty output means every line is valid. `jq` stops with a parse error and a line number on any line
that is not JSON.

## Dedupe and ordering

- Merge findings from several reviewers by `(file, line, title)`. Keep the higher severity and the
  `CONFIRMED` verdict when two disagree.
- Order the human report by severity, then file, then line.
- A pre-existing defect noticed while reviewing is listed separately in prose ("Noticed, not
  introduced") and is not emitted as a finding line.
