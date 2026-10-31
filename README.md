# STEM Task Factory

Generate medium-difficulty STEM programming tasks as Harbor task packages using
an author model and a different reviewer model.

## Current generation architecture

```text
Author proposal → reviewer feedback → one author repair, if needed
              → author implementation and tests → offline packaging
```

Each candidate receives **one reviewer call**. The initial proposal and optional
repair are two proposal versions total: `max_revisions: 1` counts the one repair.
Older generation configs are capped at one repair. There is no second review or
implementation audit. A passing initial proposal proceeds directly to implementation.
The author model also serves as implementer, using the latest proposal and feedback.

Initial reviewer findings remain in evidence. Repaired proposals are marked
`repaired_without_rereview`; packaging does not claim the repair was independently
verified. Package failures preserve diagnostics and do not start another repair loop.

## Generate two tasks

1. Use an existing Python 3.11+ interpreter and authenticated Codex CLI.
2. Copy `config/generation.models.yaml` to a local run config, such as
   `config/my-run.models.yaml`.
3. Set the repository path, a readable existing-task inventory directory, and a
   fresh output directory under `task/`. Config paths resolve relative to the config
   file, not the terminal working directory. Output must be separate from inventory.
4. Configure an exact accessible author model and a different reviewer model.
   Use the stronger model for author/implementer and a less expensive capable model
   for reviewer. Copy the author role exactly to implementer and update the model
   entitlement references. Availability depends on the account; model names alone
   do not prove access.
5. Configure the selected inference transport, then set `execution.live_enabled`
   to `true` for the run you intend to execute. Templates ship with live execution
   disabled and placeholder credentials/model evidence.

Run these commands from the repository root with your existing interpreter:

```console
python -m stem_factory --config config/my-run.models.yaml generate --target 2 --dry-run
python -m stem_factory --config config/my-run.models.yaml generate --target 2
python -m stem_factory --config config/my-run.models.yaml report
```

Use `--target 2` explicitly; the CLI default is five. The target is the total
accepted count for that output directory. Repeating the same command resumes it;
it does not request two additional tasks. Changed configuration requires a new
output directory. Set `max_candidates: 2` if you want only two candidate attempts;
a higher candidate limit allows replacements for failed candidates.

On Windows, replace `python` with your installed interpreter if the Windows Store
alias is unavailable. The optional `scripts/stem-factory.ps1` wrapper uses
`STEM_FACTORY_PYTHON` when set.

For a copyable instruction to give your terminal coding agent, use the
[task generation prompt](docs/TASK-GENERATION-PROMPT.md).

## Inference transport and authentication

Generation supports the built-in Codex CLI through either explicitly configured
Docker transport or an audited strict isolation launcher. It does not currently
support mixing Codex and Claude in generation mode. The legacy `run` workflow has
separate adapter support and different review/validation behavior.

The shipped generation template selects Docker transport. Configure its existing
immutable CLI image ID and dedicated authentication volume before a live run.
Docker in this mode runs the author/reviewer CLI; it is separate from Docker used
later to execute generated tasks. Selecting strict transport instead requires its
reviewed launcher and evidence. See [Docker setup](docs/DOCKER-GENERATION.md) and
[strict generation setup](docs/GENERATION-ONLY.md).

Authenticate through the selected CLI's normal interactive flow. Keep credentials
out of config files, prompts, task packages, and Git. An authoring login does not
establish model entitlement or authenticate a later Harbor evaluation agent.
Dry-run performs static checks without model requests, container startup, or output
creation. It cannot establish live authentication, account limits, or runtime readiness.

## What gets validated

The reviewer assesses difficulty, correctness, solvability, ambiguity, testability,
novelty and the supplied environment context. The author receives actionable feedback.
Only Python 3.13 standard-library tasks with a single `/work/task.py` submission
are supported by this profile. Hidden tests require at least eight named unittest
cases; the bundle also includes a private reference and conceptual mutants.

The factory inspects existing task metadata and Dockerfile evidence read only,
fingerprints the environment context, and supplies it to authoring and packaging.
An environment change after the repair limit prevents stale content from publication.

Generation validation checks package structure, exact templates, Python syntax,
TOML metadata, environment fingerprints, integrity, novelty heuristics and leakage.
It does **not** execute generated Python, build task images, or run Harbor. An
`offline_valid` result establishes structural validity, not functional correctness,
verified difficulty, or Harbor compatibility. Reviewer status is reported separately.

The template build contexts keep reference solutions and hidden tests out of the
agent environment. Do not mount the whole author package into an evaluated agent.

## Output and recovery

```text
task/<run-id>/
  accepted/<task-id>/       packaged tasks
  requests/                prompts, schemas, responses and usage evidence
  agent-work/              CLI workspaces and transport diagnostics
  staging/                 unpublished packages
  failed/                  failure evidence and any partial package trees
  validation/              offline validation reports
  state.json               durable progress and publication hashes
  report.json              review, package and execution statuses
  events.jsonl             lifecycle events
```

The package contains `instruction.md`, `task.toml`, `environment/`, `solution/`,
`tests/`, and private `authoring/` evidence. Publication is atomic and refuses to
replace an existing destination. Modified accepted packages stop recovery.

Interrupted requests with uncertain provider completion require deliberate
`--retry-uncertain` after inspecting evidence. Use `--recover-lock` only when the
previous process is dead. Authentication and provider usage-limit failures stop
the run. There is no factory-wide token, model-call, spend or elapsed-time cap;
per-request timeouts, output bounds and candidate/repair limits remain.

Generated output and local run configs are ignored by Git. They remain available
locally and should be exported deliberately if you want to share task packages.

## Harbor execution is a later stage

Harbor benchmark automation is not implemented by `generate`. The CLI also blocks
`validate` when given a generation config. Do not treat an offline-valid package as
a successful Harbor trial.

The intended later gate is Docker/Harbor compatibility → Oracle reference passes
→ NOP empty submission fails → chosen evaluation agent runs → rewards/logs report.
Missing rewards or infrastructure errors must not count as an expected NOP failure.
Model evaluation needs its own configured agent authentication.

The legacy `run`, `doctor`, and `validate` commands use `config/models.example.yaml`
or another non-generation config. They retain their separate runtime validation
and review/audit behavior; they are not the shorter generation architecture.

## Development and checks

The source uses Python's standard library. Shipped `.yaml` configs contain JSON,
a valid YAML subset; ordinary YAML requires the optional PyYAML extra. Duplicate
keys, unknown fields, malformed model responses and invalid schemas fail validation.

```console
python -m unittest discover -s tests -t .
git diff --check
```

The latest offline review passed 129 tests. Tests use mocked provider/container
operations and local subprocess checks; they do not establish live model access or
Harbor execution. See the [end-to-end review](docs/END-TO-END-REVIEW.md).

Additional documentation: [generation details](docs/GENERATION-ONLY.md),
[Docker transport](docs/DOCKER-GENERATION.md), [legacy pilot](docs/PILOT.md), and
[historical validation](docs/VALIDATION.md).
