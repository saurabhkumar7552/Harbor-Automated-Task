# Repository reconnaissance

Inspected before implementation on 2026-10-30. This report describes read-only
observations; it is not a claim that a generated package ran in Harbor.

## Existing work preserved

The worktree already contained user-authorized, uncommitted edits to revision
review behavior, budget controls, configs, docs, and account-run evidence. Those
changes were inspected and left in place while this task was added. The target
`F:/GITHUB/test/tasks/calculate-average` contains 147 files. Its directory was
read only in this task; no file under it was written. Git status for the target
repository could not be read because access to its `.git` directory was denied.

## Factory behavior found

- `Factory.step` records one integer `revision` in durable `state.json`, and
  `revise_or_reject` increments it when a failure returns to authoring. It counts
  repairs per candidate and survives resume.
- Proposal review failures and implementation-audit failures both feed the same
  repair counter. Before this change, reaching the configured limit rejected the
  candidate. The prior local revision change skipped proposal review on revision 3,
  but the final review result and package progress were not represented separately.
- Author and reviewer are distinct configured roles. Generation shares a fresh
  request journal; the reviewer does not receive `difficulty_rationale`. This is
  prompt separation, not proof of statistically independent models.
- `packaging.py` owns Harbor 1.3 templates for `instruction.md`, `task.toml`,
  environment and verifier Dockerfiles, a private solution script, and hidden tests.
  `static_check` validates package structure, metadata, templates, source syntax,
  and leakage. The generation validator previously went further and built images
  and started containers.
- Candidate phases and call transcripts are durable. The prior report summarized
  candidates mostly as accepted/rejected and did not separately expose review,
  package, offline-validation, or Harbor-execution state.

## Target and Harbor evidence

The only task directory under `F:/GITHUB/test/tasks` is `calculate-average`.
Its authoritative `task.toml` declares schema 1.3, `/work/average.py`, a public
agent network mode, a no-network separate verifier, Linux, 512 MiB, one CPU, and
600-second build timeouts. The agent Dockerfile uses
`python:3.13.0-slim-bookworm`, `/work`, and no extra package installation. Its
environment `.dockerignore` keeps the build context to the Dockerfile. The
verifier Dockerfile is separate and copies only its runner and hidden test file;
`test.sh` writes scalar reward data to `/logs/verifier/reward.txt`.

The installed user-site Harbor source is readable. `harbor.models.task.config`
declares default task schema version 1.3, and `harbor.models.task.task` contains
the task-directory validator. These files were inspected statically. No Harbor
command or task execution was run. The factory profile intentionally keeps its
existing `/work/task.py` submission interface, Python 3.13 standard library,
and separate verifier; the example's function name and `/work/average.py` path
are not copied into new tasks.

## Boundaries

Offline checks include prompt/schema validation, scope and novelty checks, package
file/TOML/template checks, Python parsing, secret/leakage checks, and environment
evidence fingerprinting. A real image build, container execution, model request,
and Harbor benchmark remain separate runtime checks and are not claimed by an
offline-valid package.

## Remaining uncertainty

The target checkout's Git status was not accessible. The Docker image tag is not
an immutable digest, and this inspection did not establish its exact installed
package inventory or runtime behavior. No inference, Docker build/container start,
Harbor execution, authentication change, commit, or push was performed as part of
this repository implementation task.
