# Isolated one-candidate pilot: integration plan

Status: documentation-only preparation on 2026-10-29. Live execution remains
disabled. This plan does not authorize model inference, authentication changes,
installation, environment startup, or system changes. Cost-related implementation
is deferred by the user and is outside this plan.

## Evidence and model status

Read `PILOT.md`, the pilot-preparation report and its configuration, test and
environment evidence, and the actual adapter/config/validation/process code.
Older on-disk environment findings are superseded where explicitly stated below.

The configured role identities remain:

| Role | Configured identity | Verified access |
| --- | --- | --- |
| Author | REPLACE_WITH_VERIFIED_AUTHOR_MODEL_ID | No |
| Reviewer | REPLACE_WITH_DIFFERENT_VERIFIED_REVIEWER_MODEL_ID | No |
| Implementer | REPLACE_WITH_VERIFIED_IMPLEMENTER_MODEL_ID | No |

This turn's `codex debug models --bundled` returned exit 0. None of these
placeholders is a bundled model ID. Bundled metadata does not prove entitlement.
The preceding normal-context refreshed catalog also did not establish per-model
account authorization. No identities were substituted.

A normal-context `codex login status` check this turn returned exit 0 and reported
ChatGPT authentication; only boolean status fields were displayed. In the current
restricted context, USERPROFILE is populated but the Windows UserProfile known
folder remains empty, and CODEX_HOME is unset. Normal authentication does not prove
that the future isolated CLI can resolve its home or use its required credentials.
No credential file was opened directly, copied, printed or modified by these checks.

No connected tool exposes this account's Codex workspace model entitlements. Obtain
non-secret account/workspace confirmation of two exact, distinct model IDs enabled
for the signed-in user on Codex CLI before selecting author/reviewer. Both fields
remain placeholders until then. Product surfaces and authentication methods have
separate access boundaries; a ChatGPT picker or public catalog alone is insufficient.
See [workspace model availability](https://learn.chatgpt.com/docs/enterprise/workspace-model-availability).

## Current tool visibility

| Tool or source | Restricted host context, checked this turn | Normal Windows context |
| --- | --- | --- |
| Embedded Python 3.13.0 | Runs through its absolute path | Existing installation |
| Factory/test sources | Readable; relevant test files present | Existing checkout |
| Codex 0.165.0 | Help and bundled catalog work; home lookup fails | Login status exit 0 this turn |
| Docker CLI | File metadata access denied | Exact executable path confirmed this turn |
| Harbor user site | Directory access denied; not importable by default | Harbor 0.20.0 and TaskConfig/Task imports pass this turn |
| Hyper-V | Get-VM command exists; inventory raises VirtualizationException | Same inventory failure this turn |

Verified paths:

```text
Python: C:/Users/hp/AppData/Local/Temp/calculate-average-python313/python.exe
Codex: C:/Users/hp/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe
Docker: C:/Users/hp/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe
Harbor site: C:/Users/hp/AppData/Roaming/Python/Python313/site-packages
Factory: F:/GITHUB/stem-task-factory
Existing tasks: F:/GITHUB/test/tasks
```

The Python runtime is temporary; this plan does not install or move it. The Windows
registry reports build 26300.9711, Professional. This version observation and the
installed `codex sandbox --help` interface do not certify MXC runtime compatibility.
WindowsSandbox.exe, VBoxManage.exe and vmrun.exe were not resolved on current PATH.
That is not a whole-computer absence finding. No Hyper-V workload is verified.

Earlier read-only normal-context checks reported Docker client/server 29.8.1,
Linux, and an existing python:3.13.0-slim-bookworm image. They are historical facts,
not repeated checks this turn. Because WSL running-state changed during those prior
daemon queries, this turn performed no daemon, container or distribution queries.
No containers, distributions or VMs were started.

There is no configured/verified intended model-confinement launcher yet. Thus no
tool can be certified available *inside that future environment*. The restricted
host shell used for these checks is a separate boundary.

## Full launcher contract and gaps

`Adapter.invoke()` prefixes the provider argv with role.launcher. It runs without
a shell, sets cwd to the request workspace, sends prompts on stdin and captures
bounded stdout/stderr. The host currently supplies its inherited environment.
The launcher is trusted executable configuration, not model-produced code.

| Required property | Existing support | Remaining gap / required evidence |
| --- | --- | --- |
| Restrict model filesystem access | Empty per-request workspace; native sandbox interface exists | Audited whole-CLI policy allowing only request files plus necessary runtime/auth resources; repository, user-home data and host sockets excluded from tools |
| Minimal provider authentication | Normal ChatGPT CLI login exists | Supported approved auth integration within confinement, without credential copies in repository/prompts/logs or model-readable credential exposure |
| Deny model tools and subprocesses | Codex requests read-only native sandbox | No verified complete tool/process denial; read-only mode is insufficient |
| Disable hooks/plugins/MCP/skills/discovery | Adapter passes --ignore-user-config and --ignore-rules | These flags alone do not prove all discovery/tooling is disabled; require supported controls and confinement evidence |
| Only necessary provider network access | No audited endpoint policy configured | Enforced egress policy; remote/provider-hosted tools must also be addressed |
| Preserve exact argv, stdin/stdout/stderr and exit code | Existing argument-array process transport | Launcher must preserve this behavior without adding shell interpretation or model overrides |
| Schema/workspace path mapping | Windows adapter writes an absolute response-schema path | Prove mapping if using another OS; fixed Windows .exe cannot execute inside Linux |
| Process-tree cleanup | Host timeout/output bounds and taskkill handling | Launcher must independently ensure no surviving children after exit, timeout or cancellation |

Officially supported Windows sandbox building blocks include MXC and the legacy
elevated implementation; the unelevated implementation has weaker isolation.
Existing Docker could supply filesystem/process containment components. An existing
audited VM could also be evaluated if discovered. None is currently verified to
satisfy every row above. A Docker daemon is not itself an isolation launcher.
No claim is made that an endpoint proxy, credential broker, tool-denial policy or
appropriate role-runner image is installed. See [Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox).

## Smallest conditional implementation

1. Resolve account facts first. Record the selected exact author/reviewer IDs and
   the non-secret source confirming Codex CLI entitlement. Keep all existing
   placeholders and live_enabled=false until that evidence exists.

2. Prefer an existing audited Windows-native launcher if one can be supplied.
   This preserves the installed .exe paths and avoids Linux/Windows schema-path
   translation. Require its documented policy to satisfy every contract row.
   Do not add a passthrough launcher or weaken required properties. If there is
   no qualified mechanism, stop with a concrete external setup proposal for user
   approval; do not invent a universal sandbox wrapper.

3. Separate trusted orchestration from model confinement. The trusted factory
   needs read-only task inventory and access to Docker for local verification.
   Model processes must not receive repository mounts, Docker sockets or broad
   user-home access. Keep Docker access confined to the trusted validator side.
   A supported managed profile adjustment for that trusted side requires a
   separately reviewed approval. Do not run the whole factory unrestricted as a
   substitute for an audited launcher.

4. Correct the preflight boundary in a small tested change once the launcher is
   specified. Currently Adapter.inspect() runs version/help directly on the host;
   Adapter.invoke() uses the launcher. Extend inspection to distinguish host
   availability from actual launcher-context availability and fail closed if the
   latter cannot be checked. Resolve launcher existence before launching probes.
   Use supported non-inference version/help/auth-status checks; report auth as
   status fields only. Validate the actual runtime/path/auth context without
   exposing auth data. For Linux/container launchers, separately design the
   executable/path mapping because host-path checks cannot validate Linux paths.

5. Require the launcher to supply a minimal environment and a supported auth/home
   resolution mechanism. The inherited environment in Adapter.invoke() is not an
   allowlist. Add a launcher-specific environment policy only after its required
   OS/provider inputs are established. Do not add speculative Codex configuration
   keys, synthesize opaque sandbox-state JSON, or copy credential files.

6. Connect known validator paths using the existing schema, after trusted-context
   access is established: validation.docker_executable to the verified executable,
   validation.harbor_python to the existing embedded Python, and
   validation.harbor_site_packages to the verified user site. No schema expansion
   or package installation is needed for those path fields. Path corrections alone
   cannot fix permissions or model isolation. Leave the current pilot file
   unchanged until these corrections can be verified in its intended context.

7. After any source changes, add focused offline tests for launcher-context
   inspection, missing/failed launcher rejection, exact argv/stdio/exit behavior,
   non-inference auth classification, and path mapping if applicable. Use dummy
   secrets/sentinel files and a fake provider executable for confinement checks.
   Prove denied repository/home/socket reads, model subprocess/tool execution,
   discovery, unexpected egress and surviving-child cleanup. Operating-system
   confinement probes require an already-authorized mechanism and separate approval
   where they create sandbox/VM/container state. Fake tests cannot prove real OS
   confinement. Run the existing suite only after source changes; then safe dry-run.

## Approval and stopping points

Documentation and read-only checks are complete. Actual account settings changes,
authentication changes, software installation, policy/firewall/system changes,
container/VM/distribution startup or provisioning require a concrete proposal and
approval before action. No such action was performed here. Explicit authorization
for a later live run remains separate; cost-related work is deferred.

Next safe action: obtain non-secret confirmation of two distinct Codex CLI model
entitlements and the location/documentation of an existing audited isolation
launcher, if one exists. Existing command help/catalog cannot supply those missing
facts. Until then the model placeholders and live lock stay unchanged.

No code changed and no tests were executed this turn. The previous 55-test result
is historical. config/pilot.models.yaml retains SHA-256
3ee4b0e278a46b6a0c9cec2be418918f6455928bcba11eb434d2452cf60550aa.
