# STEM Task Factory

Generate configurable STEM tasks as Harbor task packages using
an author model and a different reviewer model.

## Current generation architecture

```text
Author draft → reviewer feedback → author final task + implementation → packaging
```

Manifest generation makes three model calls per candidate: initial author, one
reviewer, then a final author response that contains the corrected proposal and
implementation together. The final author always receives reviewer feedback,
including a failed verdict. There is no second review, implementation audit,
reviewer-based rejection or separate proposal-repair call.

Initial findings remain in evidence. Final author output is marked
`repaired_without_rereview`, not independently approved. Packaging writes a canonical
submission-artifact section and uses requirement IDs `R001`, `R002`, etc. Traceability
wording or missing coverage produces visible diagnostics rather than rejecting the
task. No semantic coverage is claimed for unresolved labels.

Offline-valid packages publish under `accepted/`. Incomplete or unsafe-to-render
packages are preserved under `drafts/` with `needs_attention` status, their original
model responses and diagnostics. They are not labeled rejected or offline-valid.
They count toward the requested candidate count, so there is no replacement loop.
Account, transport and unknown-completion errors still stop the run with evidence.

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

`--target` overrides `generation.request.count`; without either, the default is five.
The shipped template requests two. For manifest generation, the target is the total number of completed candidates
(valid packages plus drafts needing attention) in that output directory. Repeating the same command resumes it;
it does not request two additional tasks. Changed configuration requires a new
output directory. Set `max_candidates: 2` if you want only two candidate attempts;
manifest candidates needing attention remain preserved rather than replaced.

On Windows, replace `python` with your installed interpreter if the Windows Store
alias is unavailable. The optional `scripts/stem-factory.ps1` wrapper uses
`STEM_FACTORY_PYTHON` when set.

For a copyable instruction to give your terminal coding agent, use the
[task generation prompt](docs/TASK-GENERATION-PROMPT.md).

## Flexible task configuration

Add this fragment inside the existing generation configuration (keep subjects,
transport and entitlement settings). The shipped template already includes it:

```yaml
generation:
  subjects: [Physics, Chemistry, Mathematics]
  request:
    count: 5
    difficulty: medium
    language: auto
    tools: auto
    dependencies: auto
    submission_format: auto
    constraints:
      network_during_evaluation: false
      reproducible_environment: true
  workflow:
    reviewer_passes: 1
    author_repairs: 1
```

Difficulty accepts `easy`, `medium`, or `hard`. `auto` lets the author choose; an
explicit language or submission format must match exactly. Tools and dependencies
accept `auto` or arrays of exact selections. For tools, array entries are canonical
tool names; the author declares versions and purpose separately. An empty array
means none. Subjects are canonical labels, and the author puts narrower descriptions
in a separate `specialization` field. Manifest subjects rotate by candidate index,
so failed candidates do not stall rotation. Invalid labels produce expected/received
feedback. Dependencies, setup, test IDs, requirements and artifacts are carried in
`authoring/manifest.json` and validated against the same request used by all phases.

Manifest generation always uses one reviewer pass and one final author response.
The older author_repairs/max_revisions controls do not create additional manifest
loops or skip finalization; keep both at one for clarity. Legacy Python generation
retains its separate repair behavior.

Both selected task images must be Linux images with `/bin/sh` and standard POSIX
utilities for the factory wrappers. Setup steps are declared Docker RUN commands;
they are stored during authoring and only execute at a later container build gate.
Evaluation network settings are configurable and distinct from build-time downloads.
Reproducible mode requests pinned tool/dependency versions and reports incomplete
version declarations as diagnostics. Version-tagged images are accepted but not immutable;
image resolution, actual dependency availability and reproducibility need runtime
verification. The factory does not invent image digests or prove those properties.

See [manifest format and migration](docs/FLEXIBLE-GENERATION.md) for the schemas,
command locations and limitations.

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
The new template uses the `manifest-v1` profile: the author chooses language, tools,
dependencies, submission artifacts and verifier according to `generation.request`.
The reviewer checks the proposal and test plan; executable tests are produced later.
The public agent context contains only declared starter files. The private reference
and verifier have separate file groups and commands. There is no universal Python,
`/work/task.py`, or eight-unittest requirement in this profile.

Existing configs without `generation.request` retain the legacy Python 3.13
standard-library profile and its single `/work/task.py` submission. Use a fresh
output directory when migrating those configs to manifest generation.

The factory inspects existing task metadata and Dockerfile evidence read only,
fingerprints the environment context, and supplies it to authoring and packaging.
An environment change after the repair limit prevents stale content from publication.

Generation validation checks package structure, exact templates, declared traceability,
TOML metadata, environment fingerprints, integrity, novelty heuristics and leakage.
Legacy Python packages also get Python syntax checks. Manifest source syntax,
compilation, setup commands and verifier behavior remain unchecked offline.
It does **not** execute generated code, build task images, or run Harbor. An
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
  drafts/                  manifest candidates needing attention and diagnostics
  failed/                  legacy failures and historical partial package trees
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
the run. After resolving login, model access or quota, retry a cached account
failure explicitly with `generate --retry-account-errors` (or `run` for the legacy
workflow), using the same config and target. The failed request/result/transcript
are archived under `requests/<key>/attempts/`; the new attempt uses a fresh managed
workspace. If access is still blocked the run stops after that attempt. This flag
does not bypass Docker cleanup blocks, changed request identities or unknown
completion; uncertain retries retain their separate flag. There is no factory-wide token, model-call, spend or elapsed-time cap;
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

The feedback-pipeline offline suite ran 165 tests with one skipped and no failures,
plus a passing five-package/15-call regression, including
configurable difficulty and non-Python task packages. Tests use mocked provider/container
operations and local subprocess checks; they do not establish live model access or
Harbor execution. See the [end-to-end review](docs/END-TO-END-REVIEW.md).

Additional documentation: [generation details](docs/GENERATION-ONLY.md),
[Docker transport](docs/DOCKER-GENERATION.md), [legacy pilot](docs/PILOT.md), and
[historical validation](docs/VALIDATION.md).

Manifest completion with drafts returns a nonzero CLI exit status so automation does
not mistake incomplete packages for validated output. Inspect `completed_candidates`,
`accepted`, `needs_attention`, `diagnostic_phase` and `packaging_warnings` in the report.
