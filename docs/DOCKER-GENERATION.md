# Generation using ordinary Docker

The user approved replacing complete tool denial/credential separation with the
reference project's container-confinement and standard CLI-authentication workflow.
`config/generation.models.yaml` now explicitly selects `generation.transport: docker`.
Existing profiles default to `strict`; `require_strict_isolation()` and its empty
trust registry are unchanged. Docker is an explicit alternative, never a fallback.

## Implemented behavior

- One Linux image supplies guest `codex` for every role. Author/implementer remain
  `gpt-6.1-sol`; reviewer remains `gpt-6.1-terra`, using the user's attestation.
  Target five, medium difficulty, two revisions and task-validation behavior remain.
- Every model request gets a new container and its own read-only bind at `/work`,
  containing only the response schema. Prompts arrive through stdin. The repository,
  benchmark tree, host home, Docker socket and sibling workspaces are not mounted.
- Non-root UID 1000, read-only root, dropped capabilities, no-new-privileges, bounded
  CPU/memory/PIDs, private tmpfs and a guest timeout are requested. A controller
  timeout/output limit also bounds transport. Native Codex `--sandbox read-only`,
  `--ignore-user-config`, `--ignore-rules` and `--ephemeral` are retained.
- The model container uses ordinary bridge networking. This does **not** restrict
  egress to provider endpoints or deny every built-in/hosted tool. Tools remain
  available subject to CLI and container restrictions.
- Standard CLI state lives in a dedicated named credential volume mounted at
  `/codex-home`. It is writable so normal authentication refresh can persist.
  Guest tools may read and potentially alter it: this is **not credential isolation**.
  Containers/workspaces are fresh; credential state is shared. Do not provision the
  volume with unrelated files, repository content or a copy of the entire host home.
- Only an existing local Linux image ID (`sha256:` plus 64 hex digits) and an
  existing plain local volume are accepted. Mutable image tags, host-path credential
  mounts, bind-backed volume options, remote daemon endpoints, arbitrary launchers
  and forwarded host credential environment variables are rejected. The factory
  never builds, pulls, creates an auth volume or signs in automatically.
- All handled completions, errors, timeouts and cancellation attempt force removal,
  including anonymous volumes, then query container absence. Uncertain cleanup
  blocks both roles and writes `generation-output/docker-cleanup-blocked.json`
  to prevent retries after controller restart. This marker is never removed
  automatically; investigate the named container before clearing it. If disk
  persistence fails, only the current controller's in-memory latch is guaranteed.
  The guest timeout adds a separate
  lifetime bound, but hard controller termination and adversarial cleanup enforcement
  need real runtime tests; mocked tests do not establish those guarantees.
- JSONL parsing and strict proposal/review/audit schemas remain. Failed task
  validation still halts; generated task code runs only through the existing offline
  validator. Accepted output is `generation-output/accepted`; failed diagnostics
  remain `generation-output/failed`. No Harbor benchmark route was added.

The CLI contracts come from official OpenAI documentation for
[structured non-interactive output](https://learn.chatgpt.com/docs/non-interactive-mode),
[normal authentication and refresh](https://learn.chatgpt.com/docs/auth), and
[Codex state locations](https://learn.chatgpt.com/docs/config-file/environment-variables).
Container compatibility for the chosen image remains unverified until tested.

## Historical local observations

The shipped template has live execution disabled and no image/auth volume selected.
The observations below describe a previous local setup, not the current template.
Following the user's separate build/test approval,
the Linux amd64 image was built and `generation.docker.image` is now pinned to
`sha256:f64186ca7ee2bd2fc2df5e76b91ee9a8408581f5aeec99466522deede50e0169`.
The credential-free health command exited 0 and reported `codex-cli 0.165.0` with
the required CLI interface. Both network-disabled test containers were removed;
an independent Docker inventory found no remaining `stem-model-` containers.
See the `generation-configuration/docker-image-build.log` (historical local evidence; cleanup pending),
`generation-configuration/docker-image-health.json` (historical local evidence; cleanup pending) and
`generation-configuration/docker-image-checks.json` (historical local evidence; cleanup pending).

After separate sign-in authorization, the dedicated plain local volume
`stem-factory-codex-auth` was created without reusing an existing work volume.
The user completed the device flow in a visible console/browser. An isolated,
network-disabled `codex login status` check exited 0; raw authentication output
was not saved and credential files were not opened/copied by the agent.
`generation.docker.auth_volume` now names that volume. Sign-in/status containers
were removed and volume metadata was checked without inspecting its contents.
See the `generation-configuration/docker-sign-in-result.json` (historical local evidence; cleanup pending).
Saved login presence does not establish model entitlement, token refresh success,
adversarial isolation, schema-bind compatibility or task-runtime correctness.

`generate --target 5 --dry-run` remains static and starts nothing. It reports the
new contract honestly and never claims live readiness. Restricted filesystem
visibility may hide Docker's executable even though it was reachable from the
previously approved host context; this is an execution-context requirement, not
proof that Docker is absent.

## Image provisioning recipe — completed after approval

The reviewed recipe is `docker/codex/Dockerfile`. It requires an explicit numeric
Codex package version and contains no credentials or copied repository content.
The following build was approved and completed using the historically observed
CLI version. The installed package was then verified by the offline health probes:

```powershell
& 'C:/Users/hp/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' build --pull=false --build-arg CODEX_VERSION=0.165.0 --tag stem-factory-codex:0.165.0 docker/codex
& 'C:/Users/hp/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' image inspect stem-factory-codex:0.165.0 --format '{{.Id}}'
```

The build downloaded the Node base and installed Codex inside the image. It did
not replace the Windows Codex installation. The actual immutable ID returned by
Docker inspection was recorded in `generation.docker.image`.

The explicit non-inference operation, also completed after approval, is:

```powershell
& 'C:/Users/hp/.local/bin/python3.15.exe' -B -m stem_factory --config config/generation.models.yaml generation-health
```

This starts two disposable containers with **no network, credentials, workspace or
prompt**: only `codex --version` and `codex exec --help` are permitted. It also
checks cleanup. It works with live disabled and auth volume unset. Supplying a
prompt, workspace or network-enabled request through the health path is rejected.
Passing health confirms CLI compatibility only, not model access or adversarial
confinement. No authentication or inference request occurred.

## Authentication — completed after separate approval

The user explicitly authorized Codex sign-in. After checking for a volume-name
collision, a new `stem-factory-codex-auth` volume was created. A constrained,
non-root container mounted only that volume at `/codex-home` and ran
`codex login --device-auth`; authentication was displayed locally in the visible
console instead of captured in project logs. No repository/home/socket was mounted.
The login status check in a fresh network-disabled container exited 0. The volume
name was then saved in the generation configuration; live execution remains false.
No host credential file was inspected or copied. Model access must still hold
for this authenticated deployment; status success is not entitlement proof.
Validate mount boundaries, native sandbox compatibility, cancellation, resource
limits and cleanup with dummy data before enabling live generation. Health success
does not itself enable inference or certify generated task quality.

## Offline verification

The new mock transport tests cover configuration rejection, disabled/missing runtime
gates, local context selection, scoped mounts, guest argv and schema paths, bounded
transport, timeout/overflow/cancellation cleanup, shared cleanup failure lockout,
malformed responses, credential-free health and all five simulated acceptances
through the actual Docker adapter. All Docker processes/provider responses are
mocked; fixture code is never executed. See
`generation-configuration/docker-transport-tests.log` (historical local evidence; cleanup pending).
Final suite: **106 passed in 35.738 seconds**, zero failures/errors/skips.
The static five-task dry-run exited 0; 33 Python source files parsed, the missing-image
health path failed before any process, and `git diff --check` passed. See the
`generation-configuration/docker-transport-dry-run.json` (historical local evidence; cleanup pending) and
`generation-configuration/docker-transport-checks.json` (historical local evidence; cleanup pending).
Pilot, strict-isolation source and all 147 calculate-average files were preserved.

Changed implementation files: `stem_factory/config.py`, `generation.py`, `cli.py`,
new `adapters/docker_codex.py`, `config/generation.models.yaml`,
`docker/codex/{Dockerfile,.dockerignore}`, `tests/test_docker_codex.py`, README,
GENERATION-ONLY.md and this document, plus verification logs/results. Existing
pilot, strict-isolation implementation, task validator and benchmark files remain
unchanged. No software was installed or runtime container started during the
implementation-only phase. The separately approved build/health follow-up installed
Codex in the image and ran its two offline probes. A later, separately approved
sign-in created the dedicated credential volume and saved normal CLI login there;
the agent did not read credential contents. No inference provider was called,
no real tasks generated, no commit/push made.
