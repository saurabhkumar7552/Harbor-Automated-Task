# STEM Task Factory

For the separate, live-disabled Codex-only five-task generation workflow, see
[generation-only preparation](docs/GENERATION-ONLY.md). Its `generate --dry-run`
preflight requires neither Docker nor Harbor and makes no model calls.
The generation profile now explicitly selects the user-approved
[ordinary Docker workflow](docs/DOCKER-GENERATION.md); image health and saved CLI
sign-in checks passed. Runtime boundary validation remains pending and live execution is disabled. Existing strict-isolation profiles retain
their original gate.

Author, independently review, implement and locally validate Harbor STEM tasks with
one command after configuring existing tools and model access:

```console
python -m stem_factory run --target 5
```

This factory covers Phases 1–3 only. It never starts Harbor benchmark execution,
installs software, pulls container images, edits existing tasks or benchmark results,
pushes commits, or deploys anything. No live tasks were generated during delivery.
See [inspection findings](docs/INSPECTION.md) for actual availability on this computer
and [validation evidence](docs/VALIDATION.md) for the tests performed.

## Start here

Python 3.11+ is required (3.13 matches the inspected task). The source package runs
without third-party dependencies. Shipped `.yaml` files use JSON syntax, a valid YAML
subset. Ordinary YAML additionally needs the optional PyYAML dependency; installing
it is an operator decision. Duplicate fields and unknown configuration keys fail.

From the factory source directory:

```console
python -m stem_factory --config config/models.yaml doctor
python -m stem_factory --config config/models.yaml run --target 5 --dry-run
python -m stem_factory --config config/models.yaml run --target 5
python -m stem_factory --config config/models.yaml validate
python -m stem_factory --config config/models.yaml report
```

`--config` is a global option placed before the subcommand. The default configuration
is `config/models.yaml` relative to the current directory. An optional console entry
point `stem-factory` is declared in pyproject.toml; install this local project into an
approved environment yourself if you want that spelling. No installation was done.

On this Windows computer, the existing embedded runtime is not on PATH. Use the
included wrapper, which also handles its isolated import path:

```powershell
& .\scripts\stem-factory.ps1 doctor
& .\scripts\stem-factory.ps1 run --target 5 --dry-run
& .\scripts\stem-factory.ps1 run --target 5
```

Set `STEM_FACTORY_PYTHON` to your existing interpreter if needed. The wrapper never
changes the interpreter's ._pth file or global settings. The temporary Python path
may eventually be removed by Windows; choose a persistent runtime for ongoing use.

The delivered sources are in a writable temporary directory because this session
cannot modify `F:\GITHUB\test`. Copy them into a proper checkout using your normal
filesystem access, then adjust configuration paths. The factory does not copy itself
or publish packages into the existing task tree automatically.

For a reviewed manual copy into the requested project, the optional installer checks
all file collisions first and refuses to overwrite anything (including existing
tests or documentation). It skips the existing project .gitignore. It was tested
only against a disposable fixture, never executed against F: in this session:

```powershell
& .\scripts\Install-IntoRepository.ps1 -Repository 'F:\GITHUB\test'
```

Add `/factory-output/` to your project's ignore rules yourself if desired. Reusing
an existing output directory with changed config is deliberately rejected.

## Configure models and validation

For the controlled one-candidate pilot, see [pilot preparation](docs/PILOT.md).
`config/pilot.models.yaml` is a schema-valid, **live-disabled** configuration with
one candidate, two review revisions, twelve model calls maximum and a fresh output
path. Its model placeholders deliberately remain unverified. A passing dry-run
does not authorize spending or prove account access.

Optional top-level `execution` controls are strict booleans:

```json
{"execution": {"live_enabled": false, "stop_on_validation_failure": true}}
```

`live_enabled=false` blocks runs before external probes or output creation and
also blocks request-journal invocations. `stop_on_validation_failure=true` preserves
failed artifacts, rejects the candidate, halts the whole run and refuses automatic
resume after local validation failure. Review failures still use `max_revisions`.
For compatibility, omitted controls default to true and false respectively.
Neither control is a currency spending cap; the pilot must remain disabled until
the INR 100 ceiling can be enforced and the user explicitly approves execution.

Edit `config/models.yaml`, or adapt `config/models.example.yaml`. Relative paths
resolve against the configuration file's directory. The local configuration points
at the requested repository and uses a separate factory-output directory.
The example's paths must be adjusted to your checkout location.

Each author, reviewer and implementer role specifies:

- `adapter`: codex, claude, gemini, or a registered extension.
- `executable`: the actual executable path, independent of the adapter name.
- `model`: an exact model identity verified in your provider/account. All shipped
  identities are placeholders, never guesses. The same adapter requires distinct
  author and reviewer model strings; differing aliases may still resolve to the same
  underlying model, so configure full identities where available.
- `effort`: null, or a supported effort value. Codex maps this to the documented
  `model_reasoning_effort` TOML key. Confirm support for your selected model. The
  inspected Claude interface has no --effort flag; Claude and Gemini adapters reject
  non-null effort instead of inventing flags.
- `args`: provider-specific argument array, restricted to the adapter allowlist and
  flags present in installed help. Permission, tool and model-selection overrides are
  rejected. Extend an adapter deliberately to add a verified interface.
- `timeout`, `max_output_bytes`: wall-time and combined stdout/stderr limits.
- `required_env`: environment variable **names**, such as `ANTHROPIC_API_KEY`,
  whose values must already be set. Never paste key values into YAML.
- `cwd`: optional workspace under output/agent-work only. Defaults to an isolated
  request directory. A reused cwd is operator-owned and must not contain context files.
- `launcher`: optional trusted argument-array prefix. Required for Codex and Gemini;
  see their isolation requirements below.

Set `validation.harbor_python` to an existing Python environment containing Harbor.
If its dependencies live outside its normal sys.path, set
`validation.harbor_site_packages` to that existing directory. Doctor captures Harbor
version and help only. Publication validates actual TaskConfig and Task classes in
that interpreter; unavailable Harbor blocks publication. No model-based Harbor check
or trial execution is used.

Set `validation.docker_executable` to an existing Docker executable and select a
locally present Python 3.13 Linux image. The default matches the existing easy task.
For stronger reproducibility, configure an immutable image digest. The factory records
the resolved local image ID and uses that same ID for every validation container.
It uses `--pull never`; arrange an approved image separately. Only standard-library
task dependencies are supported. There is no model-directed pip/install command.

## Authentication and actual adapter requirements

Authentication stays with each selected CLI. Authenticate interactively outside the
factory and never send passwords or keys to a model. Subprocesses inherit the selected
CLI's normal environment and authentication; environment values and auth files are
never copied into prompts or task packages. Recognized secret values are rejected from
task content and redacted from logs. Do not put private material in the task inventory.

| Adapter | Required interface | Response handling | Local observation |
| --- | --- | --- | --- |
| Codex | exec; --model, --json, --output-schema, --sandbox, --ignore-user-config, --ignore-rules, --skip-git-repo-check, --ephemeral | JSONL with exactly one completed agent_message containing strict JSON; turn usage retained | 0.165.0 help inspected |
| Claude | --print, --model, --output-format, --json-schema, --safe-mode, --tools, --strict-mcp-config, --mcp-config, --no-session-persistence | Single JSON result; structured_output or strict result JSON; usage and cost retained | 2.1.252 help inspected |
| Gemini | --prompt, --model, --output-format | Single JSON envelope with strict response JSON, stats and error handling | Unavailable locally; runtime probe required |

Doctor verifies installed help before a run; older/different interfaces fail closed.
Version/help success does not prove authentication, model entitlement, or response
compatibility. No CLI is auto-installed. Examples below use placeholders deliberately:

```console
codex login
codex login status
claude auth login
gemini
```

Use the CLI's normal interactive browser flow. OpenAI documents
[ChatGPT subscription authentication](https://learn.chatgpt.com/docs/auth).
Gemini's [official headless interface](https://geminicli.com/docs/cli/headless/)
documents its distinct response envelope. Prefer the factory over directly invoking
an agent on the benchmark repository.

Safe factory invocation after selecting actual accessible model IDs:

```console
python -m stem_factory --config config/my-models.yaml run --target 5 --dry-run
python -m stem_factory --config config/my-models.yaml run --target 5
```

### CLI isolation boundary

Claude uses safe-mode, no built-in tools, an empty strict MCP configuration and no
session persistence. Hooks, project instructions and plugins are disabled by safe-mode.
No model-produced commands are ever passed to a shell by the factory.

Codex and Gemini can expose tools or discover local customization. A read-only native
sandbox alone does not prevent sensitive file reads or outbound tool calls. These
adapters therefore require an **operator-audited external isolation launcher**. The
launcher is a real executable, receives the CLI argv appended after its configured
arguments, and must:

- confine the CLI to its empty request workspace and minimal authentication/config
  needed by that provider; never expose the repository, user home, host sockets or
  benchmark credentials to tools;
- deny subprocess/tool execution and arbitrary file access by the model, disable
  hooks/plugins/MCP/skills/project discovery, and allow only necessary model endpoints;
- preserve stdin/stdout/stderr, map absolute schema/workspace paths if using a container,
  enforce its own process-tree cleanup, and return the child's exit status.

Example configuration shape, **not an installed launcher**:

```json
{"launcher": ["/opt/company/bin/isolated-agent", "--policy", "/opt/company/stem-policy.json", "--"]}
```

A launcher path is trusted executable configuration, like an extension plugin; the
factory can check its existence but cannot prove its isolation policy. Do not use a
shell, echo/passthrough script or permission-bypass switch as a launcher. Until a
real launcher is configured, use an appropriately authenticated Claude interface
with tools disabled, or leave the unavailable adapters blocked. No universal OS
sandbox is silently invented by this project.

Codex's allowed provider arguments are --oss and --local-provider. Claude allows
--betas and --max-budget-usd. Gemini currently has no verified additional argument
allowlist. In particular, fallback models and resume-session flags are disallowed
because they weaken model identity or review isolation.

## Workflow and acceptance

The factory loads existing public instruction files as untrusted data, checks IDs
and lexical similarity, and gives the reviewer that inventory for semantic novelty
assessment. Similarity heuristics and model review can miss duplicates; they are
documented checks, not mathematical proof of uniqueness.

Author proposals include all requested specification, STEM objective, difficulty
rationale, requirements, acceptance criteria, solution strategy, deterministic tests,
dependencies, edges and output manifest. Every response is strictly validated. No
Markdown-fence removal, partial-JSON salvage, unknown fields or duplicate keys pass.

The reviewer receives the complete specification without the author's difficulty
verdict, prior reviews or prior conversations. Medium requires at least three dependent
reasoning/implementation steps, a nontrivial STEM algorithm and bounded scope. PASS
also requires complete, solvable, STEM-relevant and testable content with no defects.
Any failed gate is preserved and sent as actionable author feedback. The revision
gets a fresh review; exhausting max_revisions rejects the candidate. Model names and
fresh prompts do not establish statistical independence or prove difficulty.

Only a passing proposal reaches implementation. Models return three private artifacts
(reference Python, unittest Python, conceptual mutants) and the public instruction.
The factory creates shell scripts, Dockerfiles and metadata itself. A separate reviewer
audit checks specification alignment, ambiguity, leakage, tests, expected values,
requirement traceability and mutant plausibility. Failure returns through authoring
and a new difficulty review; it cannot silently bypass the gate.

This first repository profile intentionally supports one `/work/task.py` submission,
Python 3.13 standard library and at least eight named unittest cases. It supports
mathematics, physics, chemistry, engineering and other STEM APIs within that scope.
Proposals needing extra libraries, data files or network access are rejected instead
of running arbitrary setup commands.

Staging follows the inspected [Harbor format](https://docs.harborframework.com/tasks/overview):

```text
<task-id>/
  instruction.md
  task.toml
  README.md                 private author documentation
  environment/Dockerfile    empty public agent workspace; no hidden COPY
  environment/.dockerignore
  solution/solve.sh          fixed heredoc writer; Oracle-only
  tests/Dockerfile           separate hidden verifier
  tests/.dockerignore
  tests/test.sh              reward and test logging wrapper
  tests/driver.py            fixed unittest runner, minimum 8 cases
  tests/test_task.py
  authoring/evidence.json    proposal, reviews, implementation and provenance
  authoring/validation.json
```

The package root is an author artifact; only environment/ is the evaluated agent's
build context. Never mount the package root into that agent. Harbor transfers only
the declared artifact into the separate hidden verifier. References, hidden answers
and review transcripts are not in the evaluated workspace.

Local validation checks exact templates, UTF-8/LF, Python syntax, metadata, installed
Harbor schema, and package integrity. It builds both Dockerfiles with --pull=false
and --network none from the exact separate build contexts, records image identities,
and removes its temporary build tags afterward. It runs packaged solve.sh and test.sh
twice from independent clean work directories using direct Docker commands. It then
requires the empty starting workspace to fail and at least three distinct syntactically
valid conceptual mutants to fail by assertions, with no import/setup errors.

Containers are unprivileged non-root Linux processes, offline, root-filesystem read-only,
capabilities dropped, no-new-privileges, bounded memory/CPU/PIDs and tmpfs sizes. Tests
and submitted code mount read-only. Only disposable reference work mounts are writable;
no host secrets or Docker socket are mounted. Docker is a containment boundary with
normal container-runtime trust assumptions. Models' Python is never executed on the
host. Containers are explicitly removed even if a client times out.

Two clean successes establish basic repeatability for deterministic reviewed tests,
not universal reproducibility across platforms or proof of medium difficulty.
The exact installed schema, separate image builds and direct offline runtime checks
are the local gate; full Harbor benchmark integration stays separate.

## Output, budgets, recovery and failures

All factory writes are contained in the configured output directory, separate from
existing tasks:

| Location | Contents |
| --- | --- |
| state.json | Durable phase state, model/config identity, budgets, accepted hashes |
| .lock | Single-writer PID lock |
| requests/<candidate>-<revision>-<role>/ | Full request, schema, response/transcript, usage and error evidence; secret-redacted |
| agent-work/ | Isolated CLI workspaces and transport diagnostics |
| staging/ | Unique unpublished packages |
| failed/ | Rejected candidates, original failures and failed package trees |
| accepted/<task-id>/ | Atomically published accepted packages |
| validation/ | Local validation reports and container test output |
| events.jsonl | Structured lifecycle log |
| report.json | Last run summary; `report` also reads current durable state |

Publication is an atomic rename on the same filesystem and refuses any existing
destination. Restarting the same command resumes the same run, verifies existing
accepted hashes, reuses completed request results and handles a crash between
publication and state save. Target is the **total accepted count in this run**, so
rerunning --target 5 does not create five more tasks.

Retries, candidate count, model-call count, total workflow time and per-process output
are bounded. Cleanup has separate bounds of 15 seconds per container/build tag and
10 seconds for process termination. Execution is deliberately
serial: one in-flight provider call, no unverified provider concurrency assumptions.
Configure max_candidates high enough to replace rejected tasks.

Usage and dollar cost are recorded where the CLI exposes them. Codex/Gemini usage
usually lacks dollar cost; the report explicitly counts unknown-cost calls. The
max_cost_usd value is a **known-spend stopping threshold**, not a hard invoice cap:
an individual call can cross it, and unknown costs remain additional. Use an account
spending cap and supported provider per-call caps when a hard dollar limit is needed.
max_unknown_cost_calls bounds uncertainty by call count. The factory never claims
unknown costs are zero.

If interrupted while a request might have completed remotely, automatic retry is
blocked to avoid duplicate expensive work. Inspect its request/transcript, then
explicitly use --retry-uncertain if you accept possible duplicate usage. Completed
malformed/failed responses stay cached; the workflow revises rather than repeating
the identical paid request. A dead process lock can be recovered with --recover-lock;
active or unverifiable locks are refused. A changed configuration requires a new
output directory to preserve provenance. There is no automatic budget reset.

`doctor` and dry-run make no model calls. `run --dry-run` creates no output/task
directories. `validate --dry-run` prints packages without executing them.
`validate --static-only` returns status 2 deliberately: static checks are incomplete
validation. Exit status 0 from run means the target was reached; status 2 means
unavailable prerequisites, exhausted budgets, insufficient accepted tasks or failure.
Failed reviewers never become passing tasks just to satisfy the target.

## Extend adapters

Implement `stem_factory.adapters.base.Adapter` in an installed, trusted Python module.
Provide installed-help checks, `preflight`, `command(schema, workspace)` returning an
argv list, and `parse(text)` returning Response(value, transcript, stderr, usage,
cost_usd). Prompts arrive on stdin. No shell command templates are supported.

Register it in operator-owned configuration:

```json
{"adapters": {"my_cli": "my_company.stem_adapter:MyAdapter"}}
```

Use adapter `my_cli` for any role. Its author/reviewer model identities must differ
when using the same adapter. Your extension must enforce tool isolation and a strict
parser; add fixture tests for real installed output envelopes and rejected flags.
This is trusted code loading, not an interface a model can register dynamically.
Keep provider details inside adapters rather than factory/review/packaging logic.

## Tests

```console
python -m unittest discover -s tests -t . -v
```

Tests cover contracts, review failures, revisions, resume/caching, uncertain calls,
budgets, immutable publication, package templates, adapter envelopes, secret handling,
subprocess bounds, Docker arguments and cleanup. Fake-model/fake-container tests
exercise reaching five accepted control-plane fixtures; they are **not five independently
verified STEM tasks** and do not establish real provider or Harbor/Docker integration.
No unit test starts a benchmark or spends model usage.
