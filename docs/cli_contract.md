# ScoreForm CLI Contract

## Status and Scope

This document defines the command-line interface contract for ScoreForm's
current pre-1.0 development state. It describes the current implementation,
identifies which parts are intended to remain available, and records areas that
may change before a stable release.

This document covers command-line behavior. ScoreForm file formats and schema
contracts are documented in [`schema_contracts.md`](schema_contracts.md).

This is a compatibility and development contract, not a redesign. It does not
change scoring, QR handling, result routing, workspace routing, menu structure,
or file formats.

The installed `scoreform` command is the preferred interface. The
`python main.py ...` wrapper remains available for source-checkout and backward
compatibility use.

## Interaction Model

ScoreForm intentionally has two interaction layers.

1. **Direct CLI**
   provides file-oriented operations for scripting, regression testing,
   automation, diagnostics, development, power users, packaging, and future
   Paper Data Suite integration.
2. **Interactive menu**
   provides guided teacher-facing workflows built from the same underlying
   operations.

The two layers do not require one-to-one parity.

The menu should prioritize:

* assignment creation and management;
* roster creation, viewing, and management;
* answer-sheet generation;
* scoring scanned responses;
* QR decoding or diagnostics where useful;
* workspace settings;
* help and workflow guidance.

The direct CLI should preserve:

* scriptable, non-interactive execution;
* direct input and output paths;
* validation commands;
* setup primitives;
* diagnostics;
* automation and regression-test entry points;
* future Paper Data Suite integration points.

A command may remain direct-CLI-only when exposing it in the menu would make the
teacher workflow more technical without adding useful guidance.
`setup-assignment` is the current example: it remains available to power users,
developers, and imports, but is not a top-level teacher-facing menu item.

## Active scan review commands

ScoreForm exposes the durable QR-aware failure queue through:

```powershell
scoreform list-scan-review
scoreform list-scan-review --include-resolved --limit 25
scoreform list-scan-review --class-id english9_p2 --assignment-id quiz
scoreform resolve-scan-review <failure_id> --action rescan_needed
scoreform resolve-scan-review <failure_id> --action defer
```

List filters are `--class-id`, `--assignment-id`, and `--failure-category`.
The default list includes unresolved and deferred ScoreForm records and hides
resolved records. Malformed and non-ScoreForm records do not stop listing.

Direct resolution actions are `manual_marks`, `rescan_needed`, `cannot_route`,
`mixed_assignment`, `evidence_filed`, `dismissed_duplicate`, `other`, and
`defer`. `other` requires `--message`; `evidence_filed` requires a safe
workspace-relative `--evidence-path`. Identity flags are `--class-id`,
`--assignment-id`, and `--student-id`, and supplied identity is validated.

`manual_entry` requires answer-by-answer review and confirmation, so the direct
command points teachers to **Assignment Management > Resolve Scan Review
Items**. The same menu supports all actions. It uses compact list, detail,
action, input, and result screens and returns to the active list after a change.

## Stability Categories

These categories apply to command names and broad purpose. Unless stated
otherwise, exact prose output, whitespace, and incidental diagnostics are not a
machine-readable compatibility surface.

### Established current commands

These command families are already established in the current pre-1.0 workflow
and should not be removed or renamed casually:

* `scoreform`
* `scoreform menu`
* `scoreform help`, `scoreform --help`, and `scoreform -h`
* `scoreform version` and `scoreform --version`
* `scoreform generate`
* `scoreform score`
* `scoreform decode-qr`
* `scoreform validate-assignment`
* `scoreform validate-roster`

This category does not promise permanent v1.0 compatibility. In particular,
some positional argument forms remain awkward and may later gain clearer flag
forms with backward-compatible aliases.

### Provisional / may change

The following are intended current interfaces, but details may be refined:

* the `scoreform workspace` family, which is a recent shared-PDS integration;
* the `scoreform school-year` family, which exposes shared active school-year
  state owned by `pds-core`;
* `generate` argument structure, including the required `--rosters` marker;
* `score` mode inference from filename extension and positional argument count;
* exact human-readable output and headings;
* finer-grained exit codes;
* whether bare `python main.py` should eventually launch the menu.

Any cleanup should preserve existing useful forms where practical and should be
documented before incompatible changes are made.

### Internal or developer-only

`scoreform setup-assignment` is a supported direct operation, but its current
audience is primarily power users, developers, tests, imports, and automation.
It is not required to appear as a normal teacher-facing menu item.

Internal Python functions, module layouts, and incidental printed
representations are not part of the CLI compatibility contract.

### Future candidate

Commands and flags listed in [Future CLI Ideas](#future-cli-ideas) are design
options only. They are not implemented or reserved interfaces.

## Current Command Surface

The following syntax reflects actual current behavior.

### Launch, help, and version

```powershell
scoreform
scoreform menu
scoreform help
scoreform --help
scoreform -h
scoreform version
scoreform --version
```

* Bare installed `scoreform` launches the interactive menu.
* `scoreform menu` explicitly launches the same menu.
* The three top-level help forms print the same manually maintained help text
  and return success.
* The two version forms print `ScoreForm <version>` and return success.

### Workspace

```powershell
scoreform workspace
scoreform workspace help
scoreform workspace --help
scoreform workspace -h
scoreform workspace show
scoreform workspace set "<path>"
scoreform workspace validate
scoreform workspace reset
```

The first four forms print workspace help and return success.

### School year

```powershell
scoreform school-year
scoreform school-year help
scoreform school-year --help
scoreform school-year -h
scoreform school-year show
scoreform school-year open 2026-2027
scoreform school-year open 2027-2028 --overwrite
scoreform school-year close
```

The first four forms print school-year help and return success.

ScoreForm delegates active school-year state to `pds-core`. The state file is:

```text
<PDS workspace root>/settings/school_year.json
```

`school-year show` distinguishes a workspace that has never opened a school
year, a currently active school year, and a closed/no-active-year state.
`school-year open` opens a `YYYY-YYYY` school year with a timezone-aware local
timestamp. `--overwrite` is required to replace a different already-open school
year. `school-year close` closes the active school year with a timezone-aware
local timestamp.

Opening or closing a school year does not delete, archive, migrate, summarize,
move, or rewrite classroom data. Assignment creation can attach standards to
questions, but creating or attaching standards during assignment creation does
not record standards usage.

### Generate

```powershell
scoreform generate
scoreform generate <assignment.json> --rosters <roster.csv> [more-rosters.csv ...]
```

Actual current behavior differs from the shorthand
`scoreform generate <assignment.json> <roster.csv>` sometimes proposed in
planning notes:

* no arguments generates a generic blank template under the managed workspace;
* assignment-based generation currently requires `--rosters`;
* one or more roster CSV files may follow `--rosters`;
* assignment setup and generated answer sheets are written into the managed
  class and assignment structure.

Removing `--rosters` or adding a simpler single-roster form is future parser or
syntax cleanup, not part of this issue.

### Score

```powershell
scoreform score <scan.pdf>
scoreform score <scan.pdf> <output.csv>
scoreform score <scan.pdf> <answer_key.json>
scoreform score <scan.pdf> <output.csv> <answer_key.json>
```

Current mode inference is:

| Arguments after `score` | Current behavior |
| --- | --- |
| `<input>` | QR-aware scoring with routed results |
| `<input> <value ending in .json>` | manual scoring with that answer key and the managed default results CSV |
| `<input> <other value>` | QR-aware scoring with that value as the explicit output CSV |
| `<input> <output> <answer-key>` | manual scoring with explicit output and answer key |

The current three-argument manual form places the output CSV before the answer
key. The proposed form
`scoreform score <scan.pdf> <answer_key.json> <output.csv>` is not the current
implementation and must not be documented as working unless code support is
added in a separate compatibility-conscious change.

When `scoreform score <scan.pdf-or-image>` uses QR-aware routed scoring without
an explicit output CSV, a full-success export may apply the configured
assignment-local scan-filing mode. The mode is stored in
`<workspace>/.pds/scoreform.json` under `scan_filing_mode` and defaults to
`copy`: `copy` files a readable timestamped `_scored` copy and preserves the
original; `move` verifies the filed copy with SHA-256 and removes the original
only if its resolved parent is exactly the active workspace `scans_inbox/`;
`off` files no automatic scored-copy. Existing filed scans are never
overwritten.

Automatic scan filing does not apply to QR-aware scoring with an explicit
output CSV or to manual scoring with an answer key. If a successful QR-aware
routed batch contains multiple assignment targets, ScoreForm skips scan filing
instead of guessing a destination.

The direct settings commands are:

```powershell
scoreform scan-filing show
scoreform scan-filing set copy
scoreform scan-filing set move
scoreform scan-filing set off
scoreform scan-filing reset
```

`reset` removes only the `scan_filing_mode` key and preserves unrelated settings.
Malformed or invalid settings fall back to effective mode `copy` during scoring
and are reported by `show`. None of these modes changes Core retained sources,
QR summaries or diagnostics, failure metadata, results, or scan-review
resolution evidence.

Mode inference and extra positional-argument validation are provisional. Scripts
should use only the documented forms.

### Validation, diagnostics, and setup

```powershell
scoreform decode-qr <file>
scoreform validate-assignment <assignment.json>
scoreform validate-roster <roster.csv>
scoreform setup-assignment <assignment.json> <roster.csv>
```

* `decode-qr` accepts a supported PDF or image path and reports routing
  identifiers decoded from a ScoreForm PDS1 payload. Other payload schemas are
  rejected as invalid.
* `validate-assignment` validates one assignment JSON file.
* `validate-roster` validates one roster CSV file.
* `setup-assignment` validates both inputs, creates managed class and assignment
  folders, and copies the source files into that structure.

These operations are non-interactive when invoked directly. They must not clear
the terminal, pause for input, or invoke menu file pickers.

## Menu Contract

The teacher-facing main menu currently provides:

```text
1. Assignment Management
2. Roster Management
3. Workspace Settings
4. Help
Q. Quit
```

Assignment Management includes assignment creation, editing, and validation,
answer-sheet generation, scan scoring, read-only assignment results viewing,
and QR decoding. Roster Management includes roster creation, viewing, editing,
and validation. Workspace Settings includes show, set, validate/create, reset
actions, School Year Settings, and ScoreForm Scan Filing Mode. The scan-filing
menu shows the effective mode and offers `copy`, `move`, `off`, and reset.
Enabling `move` interactively requires typing `MOVE` after the direct-child
cleanup rule is displayed.

The Assignment Management edit workflow is menu-only. It discovers existing
classes and assignments, loads the selected canonical
`classes/<class_id>/assignments/<assignment_id>/assignment.json`, stages edits
in memory, validates the staged assignment, and writes only after explicit
`SAVE` confirmation. Canceling without saving does not write. If staged changes
exist, discard requires typing `DISCARD`.

Assignment editing can change `title`, one existing answer-key entry at a time, and
assignment-local standards alignment. It does not allow changing
`assignment_id`, `question_count`, or `choices`. Standards editing can attach,
remove, or clear existing shared standard IDs only; it does not create shared
standards, write standards usage events or ledgers, or modify the shared
standards library. Assignment editing does not regenerate answer sheets,
rescore scans, rewrite historical results, rewrite QR payloads, delete PDFs or
scan evidence, alter rosters, or change unrelated assignments.

The Assignment Management results viewer is menu-only and read-only. It
discovers classes and assignments, opens the selected assignment-local
`results.csv`, and displays a compact `Student ID`, `Name`, `Recent`, `Total`,
and `Attempts` table. Duplicate scored rows are summarized per student for
display only; ScoreForm does not choose an official grade attempt.

The Roster Management edit workflow is menu-only. It discovers existing class
rosters, loads the selected canonical class roster through `pds-core`, stages
add/edit/remove changes in memory, and writes only after explicit save
confirmation. Canceling without saving does not write. If staged changes exist,
discard requires typing `DISCARD`.

Roster editing uses shared `pds-core` roster contracts and mutation semantics.
It can add a student, edit `last_name`, `first_name`, `period`, and existing
optional fields, and remove a student from the active roster. It does not allow
changing `student_id`. Removing a student means removing that student from the
active roster CSV only; generated PDFs, class packets, assignment folders,
assignment JSON, historical results, scans, and scan evidence are not deleted or
rewritten.

During assignment creation, the standards alignment prompt allows teachers to
skip standards or select a PDS Core standards profile. Standards in the profile
are enumerated so one or more standards can be attached to one or more
questions. Assignments store durable standard IDs in their question-level
`standards` lists and persist the selected `standards_profile_id`. Shared
definitions and profiles are managed in PDS Core; ScoreForm does not create or
edit them. Profile-scoped validation checks that every selected question
standard belongs to that profile. Empty standards lists remain valid, and this
workflow does not record standards usage or add standards reporting. ScoreForm-specific assessment,
scoring, reporting, and export behavior remains module-owned.

School Year Settings includes:

```text
1. Show school year status
2. Open school year
3. Close school year
B. Back
M. Main Menu
Q. Quit
```

Replacing a different active school year requires typing `OVERWRITE` exactly.
Closing an active school year requires typing `CLOSE` exactly. Neither action
deletes, archives, summarizes, or moves data.

The menu may:

* guide the user through selecting managed classes, assignments, and scans;
* normalize paths entered at prompts;
* clear screens and pause after important output;
* recommend QR-aware routed scoring;
* omit developer-oriented direct commands.

The menu must not be treated as a replacement for the direct CLI. Packaging and
future UI work should preserve both layers.

## Workspace Contract

Workspace configuration is owned by `pds-core`. ScoreForm delegates workspace
resolution, validation, persistence, and reset behavior and must not duplicate
the shared config-file implementation.

### Resolution precedence

The current `pds-core` resolution order is:

1. an explicit root passed by application code, where applicable;
2. `PDS_WORKSPACE_ROOT`;
3. the saved user-level Paper Data Suite preference;
4. the default `~/Paper Data Suite` directory.

An active `PDS_WORKSPACE_ROOT` therefore overrides a value saved by
`workspace set`. Setting or resetting the saved preference does not clear the
environment variable.

### Managed layout

ScoreForm-managed files live under the resolved Paper Data Suite workspace:

```text
<PDS workspace root>/
  .pds/
  classes/
  scans_inbox/
  local_outputs/
```

`pds-core` validation creates the root when needed, verifies that it is a
writable directory, and creates `.pds/workspace.json`. Other folders are
created by the ScoreForm workflows that need them.

The source checkout, installed package directory, virtual environment, and
current working directory are separate concepts. None is the implicit data root
for managed ScoreForm files.

### `workspace show`

```powershell
scoreform workspace show
```

Displays:

* the currently resolved workspace root;
* the resolution source (`explicit`, `environment`, `saved_config`, or
  `default`);
* whether the root exists, is a directory, and is writable;
* the shared Paper Data Suite config-file path;
* the default workspace root.

This is human-readable diagnostic output. Its exact labels and whitespace are
not yet a machine-readable contract.

### `workspace set`

```powershell
scoreform workspace set "<path>"
```

The command:

* expands and resolves the selected path through `pds-core`;
* rejects an empty path or filesystem root;
* creates the directory when needed;
* verifies that it is writable;
* creates or refreshes `.pds/workspace.json`;
* saves the path as the shared user preference.

It does not migrate, copy, move, merge, or delete files from another workspace.
If `PDS_WORKSPACE_ROOT` is active, that environment value remains the resolved
root even after a different preference is saved.

### `workspace validate`

```powershell
scoreform workspace validate
```

Resolves the current root using normal precedence, then validates or creates it.
It verifies writability and creates or refreshes workspace metadata. It does not
migrate user data.

### `workspace reset`

```powershell
scoreform workspace reset
```

Clears only the saved user preference. It does not delete:

* the workspace directory;
* `.pds/`;
* `classes/`;
* `scans_inbox/`;
* `local_outputs/`;
* generated files, scans, results, or other user data.

After reset, the resolved root is determined again from
`PDS_WORKSPACE_ROOT`, if set, or the default root. Reset is not a cleanup or
uninstall command.

## Help and Discoverability

The required top-level help forms are:

```powershell
scoreform help
scoreform --help
scoreform -h
```

The required workspace help forms are:

```powershell
scoreform workspace
scoreform workspace help
scoreform workspace --help
scoreform workspace -h
```

Help is currently implemented with manual dispatch and manually maintained
text. It should list the intended command families, describe current scoring
modes, include workspace commands, and mention `python main.py`
compatibility.

Per-command forms such as `scoreform score --help` are not currently
implemented as structured parser help and are not part of the present contract.

## Path Handling

The path contract is:

* paths containing spaces may be quoted according to the user's shell;
* explicit input and output paths supplied to direct commands are honored;
* direct input paths are not silently relocated into the workspace;
* explicit output paths are not replaced with managed defaults;
* managed default outputs and routed class data use the resolved PDS workspace;
* the current working directory is not the implicit root for managed data;
* source-checkout paths and runtime workspace paths remain separate.

Shell quoting is responsible for delivering a quoted path as one argument.
Interactive menu prompts additionally normalize surrounding quotes for pasted
paths.

Relative explicit paths remain relative to the process working directory
because they are user-supplied paths. This is distinct from managed default
paths, which are rooted under the PDS workspace.

## Output and Error Behavior

Current output is intended for people. Scripts should rely primarily on exit
status and files produced, not exact message wording.

Expected error style:

* ordinary user, validation, and workspace errors print concise messages;
* ordinary errors should not display tracebacks;
* usage failures print a short usage message where one exists;
* unexpected programming or dependency failures may still raise normally
  during development;
* future parser work should make usage diagnostics and output streams more
  consistent.

The current implementation generally uses standard output for both normal
messages and ordinary errors. Standard-output versus standard-error placement
is not yet a stable contract.

## Exit Codes

Current reliable behavior distinguishes:

```text
0 = success
1 = usage, validation, command, or workflow failure
```

Examples that return success include help, version, workspace help, successful
workspace operations, and a normal menu exit. Unknown commands and ordinary
operation failures return nonzero, currently `1`.

The intended future convention is:

```text
0 = success
1 = command or workflow failure
2 = usage error
```

Exit code `2` is not implemented consistently today and must not yet be assumed
by scripts. A parser migration may establish this distinction later.

## Packaging Contract

The package currently defines the console entry point:

```text
scoreform = scoreform.cli:main
```

Future desktop or executable packaging should add non-technical launch paths
without weakening direct CLI access. A packaged ScoreForm launcher should
ideally support:

```powershell
scoreform
scoreform menu
scoreform workspace show
scoreform generate ...
scoreform score ...
scoreform validate-assignment ...
scoreform validate-roster ...
scoreform setup-assignment ...
```

Packaging should preserve:

* command-line arguments;
* `--help` and `--version`;
* scriptable exit codes;
* direct subcommands where practical;
* the guided menu.

On Windows, a future `scoreform.exe` should preserve the same command surface.
A GUI-only or double-click-only package must not become the only supported
distribution model if it prevents power users and automation from using the
CLI.

## `python main.py` Compatibility

`main.py` is a thin compatibility wrapper around `scoreform.cli`.

Current behavior:

* `python main.py <command> ...` supports the same direct command dispatch;
* `python main.py menu` launches the interactive menu;
* bare `python main.py` prints help and exits with `1`;
* bare installed `scoreform` launches the menu and exits normally when the menu
  closes.

The installed `scoreform` command is the preferred long-term public interface.
The wrapper is currently transitional and development-oriented, while remaining
supported for backward compatibility. Whether it becomes permanent should be
decided as part of a future formal compatibility policy.

## Backward-Compatibility Guidance

Before v1.0:

* avoid renaming established command families without a strong reason;
* preserve existing useful positional forms when adding clearer flags;
* add aliases or deprecation periods when practical;
* do not treat exact human-readable output as stable structured data;
* document intentional incompatible changes in the changelog and release notes;
* keep help text, this contract, and discoverability tests aligned.

Scoring behavior, QR payloads, schemas, routed result formats, and workspace
layout have their own compatibility concerns and must not be changed merely as
CLI cleanup.

## Future CLI Ideas

The following ideas are intentionally out of scope for the current contract
work.

### Structured parser

Consider moving manual dispatch to `argparse` or another structured parser once
the command set stabilizes. Potential benefits include cleaner help, consistent
flags, stronger argument validation, easier subcommand expansion, and reliable
usage exit codes.

### Machine-readable output

Possible forms include:

```powershell
scoreform score scan.pdf --json
scoreform validate-assignment assignment.json --json
scoreform validate-roster roster.csv --json
scoreform workspace show --json
```

JSON, CSV summaries, or both remain open design choices.

### Dry-run or preview

Possible forms include:

```powershell
scoreform generate assignment.json --rosters roster.csv --dry-run
scoreform setup-assignment assignment.json roster.csv --dry-run
scoreform workspace set "<path>" --dry-run
scoreform file-scans --dry-run
```

Dry-run behavior matters most for commands that write, copy, move, file, or
overwrite files.

### One-time workspace override

Possible forms include:

```powershell
scoreform --workspace-root "<path>" score scan.pdf
scoreform score scan.pdf --workspace-root "<path>"
```

No command-level override flag exists today. `PDS_WORKSPACE_ROOT` and the saved
shared preference remain the available mechanisms.

### List and inspect commands

Possible commands include:

```powershell
scoreform list-classes
scoreform list-assignments english9_p2
scoreform list-scans
scoreform show-roster english9_p2
scoreform show-assignment english9_p2 rj_act1_quiz
```

### Doctor or environment check

A future `scoreform doctor` could report the ScoreForm version, runtime and
dependency availability, Poppler availability, workspace resolution,
`PDS_WORKSPACE_ROOT` status, expected folders, write permissions, common setup
problems, and generated/private-folder Git tracking risks in development
checkouts.

### Explicit scoring-mode flags

Possible forms include:

```powershell
scoreform score scan.pdf --qr-routed
scoreform score scan.pdf --qr-output results.csv
scoreform score scan.pdf --answer-key answer_key.json
scoreform score scan.pdf --answer-key answer_key.json --output results.csv
```

Explicit flags may be clearer than current positional inference. Any change
should preserve existing documented forms unless there is a strong reason and a
documented migration plan.

### Quiet and verbose modes

Possible forms include:

```powershell
scoreform score scan.pdf --quiet
scoreform score scan.pdf --verbose
scoreform workspace validate --verbose
```

## Related Work and Non-Goals

This contract intersects with desktop packaging, structured logging, Paper Data
Suite interoperability, parser cleanup, schema and version contracts, scan
filing, reporting and export workflows, machine-readable output,
`scoreform doctor`, and workspace override flags.

Those areas are not automatically part of CLI contract maintenance. This
document does not implement:

* parser migration;
* JSON output;
* dry-run behavior;
* `scoreform doctor`;
* one-time workspace flags;
* desktop or GUI packaging;
* scan filing command design;
* gradebook export;
* reporting commands;
* command renaming;
* scoring-mode redesign.

## Open Questions

* Which command names and argument forms should receive a formal pre-1.0
  compatibility guarantee?
* Should every major teacher workflow have a direct CLI equivalent?
* Which menu-only workflows, if any, are acceptable?
* Should packaged Windows distributions provide a `scoreform.exe` that
  preserves every practical CLI subcommand?
* Should ScoreForm adopt a formal CLI deprecation and compatibility policy?
* Should explicit scoring-mode flags arrive before, during, or after parser
  migration?
* Should machine-readable output use JSON, CSV summaries, or both?
* When should usage errors begin returning `2` separately from runtime
  failures?
* Are one-time workspace override flags useful enough when
  `PDS_WORKSPACE_ROOT` and saved shared configuration already exist?
* Should bare `python main.py` eventually launch the menu, or remain a
  help-and-failure development invocation?
