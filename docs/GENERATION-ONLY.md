# Codex-only generation preparation

## Current profile: ordinary Docker transport

The user approved adopting the reference project's ordinary Docker/standard CLI
authentication policy. The current generation profile explicitly selects `docker`.
See [Docker generation](DOCKER-GENERATION.md) for implementation, changed security
assumptions, provisioning and verification. No strict trust record was enrolled and
the strict launcher gate below remains unchanged for `strict` profiles. Historical
findings below about the shipped profile are superseded where that document says so.

## Strict launcher preflight correction (2026-10-29)

The generation path now constructs Codex adapters with strict isolation explicitly
enabled. Strict `inspect()` is static and does not invoke host version/help checks.
Strict `preflight()`, `invoke()` and `command()` revalidate isolation evidence and
fail closed before any process or schema write. There is no automatic legacy
fallback, no health command, and no confined health/transport implementation in
this patch. Even a structurally complete, trusted static review cannot enable
execution. Changing `live_enabled` alone cannot make generation runnable.

Each role may specify `launcher_evidence` as an absolute path or null. Omission
retains legacy non-generation behavior, but blocks strict-generation readiness.
All generation roles must share the same launcher argv and evidence reference;
author and implementer must still have identical role configurations. No shipped
configuration was edited. Review bytes contribute to strict-generation config
fingerprints, so replacing evidence at the same path invalidates old run state.
Referenced binary, dependency, policy and audit-document contents are checked
afresh against the digests bound into the review.

`stem_factory/isolation.py` accepts only strict JSON review records with these
required top-level fields: `version`, `launcher`, `codex`, `policy`, `dependencies`,
`contract`, `controls`, `audit`, `runtime_binding`. Version 1 binds canonical native
executable identities/architecture, version/publisher/provenance, policy bytes and
version, dependencies, exact launcher prefix (ending in `--` and containing the
policy path), workspace/schema mapping, independent audit/negative-test documents,
dated review scope/expiry/revalidation conditions and an independently observed
policy-activation design. Required control descriptions cover filesystem, process,
tools, network, workspace, authentication, environment, cleanup, path mapping,
resources, discovery and deployment permissions. Unknown/duplicate/missing fields,
invalid dates, mismatches and inaccessible records fail closed. The functions in
that module define the exact nested schema; no sample approved record is shipped.

Static executable assessment rejects missing files/directories, scripts and known
interpreter wrappers, unsupported native formats/architectures, DLLs, traversal,
UNC/device/alternate-stream paths and reparse points in artifacts or their parents.
It uses file metadata, PE inspection and the read-only Windows GetBinaryTypeW API;
it never runs a candidate to check it. Evidence/artifacts cannot be in the configured
task inventory or output tree. These checks are not proof of loader success,
deployment ACL correctness, complete dependencies or actual confinement.

A record cannot approve itself. `TRUSTED_REVIEWS` is an empty operator trust registry;
no enrollment mechanism or actual approved record is provisioned. An independent
review decision must bind reviewer, reviewed policy and audit document as well as
the full record identity. Only tests mock these trust decisions and Windows APIs.
A path, suffix, signature, digest, publisher string or approval field alone cannot
authorize execution. Enrolling real evidence requires a separate reviewed operator
trust mechanism; editing record contents cannot enroll it.

Dry-run now reports per-role `host_artifacts`, `static_evidence`, `audit`,
`isolated_health`, `confinement` and blockers separately. `ready_for_execution` and
`ready_for_live_generation` remain false. Health is `not_implemented` and confinement
is `unverified`, including for a complete mocked review. Current evidence enrollment,
OS ACL/enforcement audit, request-bound health, authentication isolation, complete
tool denial and contained transport remain future work. No model access or sandbox
safety is verified. Model placeholders, revision limits and offline Docker task
validation remain unchanged. See the new
[patch report](launcher-preflight-patch-20261029T113237Z/REPORT.md) for current tests
and preservation evidence. The preparation results below are historical.

Prepared 2026-10-29. No live inference, real task generation, Docker operations,
Harbor execution, installation, authentication changes or commits were performed.
The existing pilot remains disabled and unchanged. Cost tracking implementation
is deferred; existing call/time limits are retained, not represented as spend caps.

## Implementation plan and inspection

1. Reuse strict proposal/implementation/review contracts, fresh reviewer requests,
   bounded revisions, novelty inventory, journal, staging and atomic publication.
2. Add a separate `generate` command/profile. Use one installed Codex executable,
   with author also implementing and a different reviewer model. Preserve the
   original `run`, `doctor` and validator behavior for existing configurations.
3. Make generation dry-run preflight read-only, without subprocesses, Docker,
   Harbor, inference or accepted output. Report unresolved entitlement/isolation.
4. Replace only Harbor's installed schema check with the repository's strict
   local template/TOML validation in this profile. Retain offline Docker execution
   for all untrusted task code. Require runtime readiness before future inference.
5. Cover orchestration and boundaries with mocked providers and run offline tests.

Inspected README.md, PILOT.md, ISOLATED-PILOT-INTEGRATION-PLAN.md, both existing
model configurations, CLI/adapters, factory, contracts, proposals/review, packaging,
validation, state/journal, process transport and tests. Existing configuration paths
refer to `F:/GITHUB/test/tasks`; that remains a read-only novelty inventory. New
output is `F:/GITHUB/stem-task-factory/generation-output/accepted`.

The original preflight combines adapter checks with Harbor/Docker doctor probes.
Harbor is unnecessary for local authoring/schema checks and is omitted from the
generation path. Docker is unnecessary for static preflight, but remains required
for actual generated-code tests under the existing containment design. The Codex
launcher is a separate model-tool security boundary and cannot safely be omitted.
No host-code execution fallback or passthrough launcher was added.

## Model selection and evidence

Read-only inspection of the existing executable at
`C:/Users/hp/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe` reported
`codex-cli 0.165.0`. `exec --help` confirms `-m, --model <MODEL>` and the adapter's
JSON/schema/ephemeral/read-only/ignore-user-config/ignore-rules flags.
`debug models --help` and `debug models --bundled` also succeeded. The bundled
catalog contains multiple model IDs, but neither bundled presence nor
`supported_in_api` proves entitlement. These probes emitted a home-directory
resolution warning in the restricted context. Authentication was not changed;
no credential files were read. Historical login findings do not establish current
isolated-runtime access. A refreshed catalog would still not establish entitlement.

The [official CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
was consulted; installed help is the evidence for this binary's supported syntax.
All model IDs remain placeholders. No account-specific entitlement evidence for
two distinct models is available here; no verification inference was attempted.

`config/generation.models.yaml` requires the same Codex executable for every role,
the identical author configuration for implementation, and distinct author/reviewer
IDs. Provider overrides, custom adapters and reused workspaces are rejected.
Each invocation passes that role's explicit `--model` value. Fresh reviewer requests
omit the author's difficulty rationale and prior feedback. A reviewer sees the full
implementation during the separate audit. This is procedural independence, not a
claim of statistical independence or guaranteed difficulty assessment.

Before a future live run, `generation.entitlements.author` and `.reviewer` must
contain objects with `model` (the matching exact ID) and `source` (a non-secret
account/workspace confirmation reference explicitly establishing Codex CLI access).
These records are operator attestations, not automatic entitlement verification.
Do not use public catalog/login evidence, credentials, or raw account diagnostics.
Distinct aliases may refer to the same underlying model; confirm actual identities.
Missing/stale evidence and placeholder IDs fail closed before calls or output.

## Workflow and validation

Default target: five accepted medium tasks. `generation.subjects` is a configurable
ordered mix: Mathematics, Physics, Chemistry, Engineering, Statistics. Subjects
rotate by accepted count so rejected candidates do not consume subject slots;
repeat a subject to increase its share. A domain mismatch rejects the proposal.
Within each subject, author proposals must define learning objective, explicit
inputs/expected outputs, constraints, units/tolerances, errors and objective
acceptance criteria. Existing contracts include requirements, solution strategy,
deterministic tests, edge cases and output manifest. Review rejects ambiguity,
inadequate tests and unsuitable difficulty.

Each candidate passes proposal review, implementation by the same author model,
and reviewer audit. Defects return to authoring and a fresh review, with at most
two revisions in the shipped profile; candidate/call/time bounds also apply.
Novelty checks compare identifiers and lexical similarity with existing and
accepted packages, plus semantic novelty review. The generation path also checks
the final public instruction. These checks can miss semantic near duplicates.

Only schema/template/syntax-valid packages whose reference passes twice in clean
offline containers, whose empty baseline fails, and whose three or more conceptual
mutants fail assertions may publish. Existing non-root, resource-bounded,
network-disabled container flags, cleanup and separate build contexts are retained.
Failed partial packages move from staging into failed diagnostics; they never
publish. Validation failure halts the shipped profile. Crash recovery and accepted
hash checks remain in place. Static-only validity cannot qualify for acceptance.

The generation validator never invokes installed Harbor schema code or CLI. Its
schema result records that Harbor compatibility is unverified. Harbor package
templates are retained for later integration, not as a claim of benchmark readiness.
No evaluation command exists in this generation route.

## Verification and commands

The existing temporary Python 3.13 executable is gone and the registered 3.13 shim
points to a missing file. Existing `C:/Users/hp/.local/bin/python3.15.exe` reports
3.15.2 and runs the offline factory suite. No runtime was installed. Generated task
runtime remains the configured Python 3.13 container, which was not started/tested.

Run the no-inference preflight from this repository:

```powershell
& 'C:/Users/hp/.local/bin/python3.15.exe' -B -m stem_factory --config config/generation.models.yaml generate --target 5 --dry-run
```

It reports the workflow, output, local Python and CLI file presence, placeholders,
disabled execution, missing launcher and deferred offline runtime validation.
Exit 0 means the dry-run completed, not that a live run is ready. It runs no
version/help/auth probes itself and makes no output directory. Other factory
commands that could invoke the original doctor/validator are rejected for this
profile; `report` is permitted.

Tests: `python3.15.exe -B -m unittest discover -v`. See
`generation-preparation/tests.json` and `generation-preparation/unittest.log` for
the expanded suite's actual results: **69 tests passed, zero failures/errors/skips**
in 32.651 seconds using Python 3.15.2. `git diff --check` passed. The actual
five-task dry-run completed with exit 0 and no generation output directory;
its result is saved in `generation-preparation/dry-run.json`.
All model providers and generation task
execution are mocked. Tests establish control-flow behavior, not confinement,
entitlements, medium difficulty or scientific correctness of real packages.

Future generation command -- **NOT EXECUTED; currently blocked**:

```powershell
& 'C:/Users/hp/.local/bin/python3.15.exe' -B -m stem_factory --config config/generation.models.yaml generate --target 5
```

Before that command can make calls: obtain entitlement evidence for two distinct
exact IDs; verify authenticated access within an audited launcher satisfying the
existing isolation contract; review that launcher's filesystem/tool/discovery/
network/process-cleanup controls; verify the existing local Docker runtime/image
and approve generated-code validation; obtain explicit user approval for live
model usage and deliberately enable this separate configuration. Do not enable
the existing pilot. Provisioning or system/auth changes require a separate concrete
proposal. No sandbox safety or model access has been certified. Paid calls remain
unauthorized, and cost tracking remains deferred.

Files changed in this preparation: README.md; stem_factory/cli.py, config.py,
factory.py; new stem_factory/generation.py, config/generation.models.yaml,
tests/test_generation.py, this document and generation-preparation evidence.
Pre-existing modifications to reporting.py, state.py, the pilot and unrelated
documentation/tests were preserved. Pilot SHA-256 remains
`3ee4b0e278a46b6a0c9cec2be418918f6455928bcba11eb434d2452cf60550aa`.
