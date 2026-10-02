# Issue #219 Slice 4 — Safe post-export local-open actions

## Scope

Slice 4 adds explicit local-open actions after a Results Analysis report has
already been created successfully.

The actions reuse ScoreForm's existing generated-output opening boundary:

```text
scoreform.generated_output_opening
```

No new shell-launch implementation is introduced.

## Teacher workflow

After successful installation, ScoreForm shows the created report directory and
files, then offers format-appropriate local actions.

For PDF and JSON:

```text
1. Open report
2. Open report folder
B. Back
M. Main Menu
Q. Quit
```

For CSV report sets:

```text
1. Open report folder
B. Back
M. Main Menu
Q. Quit
```

CSV is a multi-file report set, so there is no arbitrary "main" CSV file to
open.

## Explicit action only

Creating a report does not automatically launch the operating system.

The open boundary is reached only after:

1. scope selection;
2. format selection;
3. immutable report snapshot preparation;
4. destination preview;
5. exact `GENERATE` confirmation;
6. in-memory rendering; and
7. successful create-only installation.

Choosing Back/Main/Quit after creation performs no open action.

Cancelling before generation performs no open action.

## Existing safety boundary

File opening uses:

```text
open_generated_output_file(...)
```

Folder opening uses:

```text
open_generated_output_folder(...)
```

Those helpers already:

- reject URL-like paths;
- resolve the active workspace strictly;
- require the target to exist;
- require the expected file/directory type;
- reject targets outside the workspace, including escaping symlinks;
- route the actual OS open through Core's local-open boundary.

Slice 4 does not duplicate or weaken those checks.

## Exact created path

The workflow passes the exact workspace-relative paths returned by
`InstalledResultsReport`.

For PDF/JSON the file action uses the single installed report artifact.

The folder action uses the installed report destination directory.

No path is reconstructed from student identity or user-controlled display text.

## Fail-soft open behavior

Opening is post-export convenience, not part of report persistence.

If the local-open boundary fails:

- the report remains created;
- the workflow returns success for the export operation;
- ScoreForm reports that the report was created but could not be opened;
- no report files are deleted or rewritten;
- no retry, alternate path, or external URL is invented automatically.

## Headless qualification

Automated tests mock the opening boundary.

CI does not launch a graphical viewer or file manager.

The tests assert the exact workspace-relative file/folder passed to the
existing opening helpers.

## Mutation boundary

Slice 4 changes no report bytes and no output-custody semantics.

It does not mutate:

```text
assignment.json
results.csv
scans
standards/library.json
routes
publications
Meridian state
```

## Deferred

Core v0.6.4 dependency-floor adoption, installed v0.12 acceptance, version
updates, and release qualification remain later Issue #219 slices.
