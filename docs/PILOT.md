# One-candidate pilot preparation

Live execution remains disabled. No model inference, task generation, Harbor
evaluation, installation, authentication changes or billing changes were performed.
The existing easy task is outside all factory write paths.

## Prepared configuration and execution controls

`config/pilot.models.yaml` retains all three explicit Codex roles and their exact
unverified placeholders. Author and reviewer placeholder strings differ; this
does not establish account access or independent model identities. No alias was
substituted based on a subscription, a default, or a bundled catalog.

The pilot permits one candidate and up to three repair revisions. It has no
factory-level model-call, total-run-time, prompt-size or spend caps. Its uniquely
named output is separate from existing tasks and the default output, and has not
been created.

New optional top-level configuration:

```json
{"execution": {"live_enabled": false, "stop_on_validation_failure": true}}
```

The schema rejects unknown execution keys and non-boolean values. Omitted keys
retain historical behavior: live enabled and validation failures eligible for
revision. The pilot explicitly overrides both defaults.

The live lock is checked before CLI preflight or output creation and independently
at the request journal before reserving/invoking a call. Dry-run remains permitted.
Changing model placeholders alone cannot unlock the pilot. This is an operator
lock.

With stop-on-validation-failure enabled, failed validation reports or validation
exceptions preserve diagnostic artifacts, reject the candidate, record a durable
run halt, and prevent revisions, replacement candidates, publication and automatic
resume. Static validation failures also halt. Ordinary review rejection still
requires a fresh review and respects the existing revision limit. No Harbor
benchmark command was added.

## Model and authentication findings

Codex 0.165.0 supports `--model`, `exec --ignore-user-config`, `--ignore-rules`,
`--sandbox read-only`, `--ephemeral`, JSONL and an output schema. The adapter passes
its explicit model string via `--model`; it does not inherit the desktop model.
`--ignore-user-config` skips the user configuration while auth still uses
`CODEX_HOME`, according to installed exec help. Consequently a custom provider
configured only in a normal user config would not automatically transfer here.

Official documentation identifies user configuration at `~/.codex/config.toml`
and authentication under `CODEX_HOME` or the OS credential store. Login method,
provider and model access must be established for the factory's actual invocation,
not inferred from a ChatGPT login. See [authentication](https://learn.chatgpt.com/docs/auth)
and [configuration](https://learn.chatgpt.com/docs/config-file/config-reference).

In this restricted execution context, USERPROFILE and HOMEDRIVE/HOMEPATH resolve
to the expected user directory, but Windows' known-folder API returns an empty
UserProfile path. HOME and CODEX_HOME are unset. Codex help emits a home-resolution
warning and login status exits 1. The empty known-folder result is evidence of a
context-specific resolution problem, not proof of missing credentials or a corrupt
normal user profile. No credential file was opened. No home/auth variable was changed.

Installed `debug models --bundled` succeeds without inference. Its catalog includes
multiple exact identities, but it is compiled metadata, not entitlement evidence.
The `supported_in_api` field also does not establish account API access. All model
placeholders therefore remain unchanged. The independent reviewer still needs an
account-verified identity different from the author before any live enablement.
The implementer may share an entitled author identity if later chosen explicitly.

Run these from a normal Windows PowerShell terminal. They do not request inference
or change authentication. Do not paste full diagnostics/configuration into chat.

```powershell
$codexExe = 'C:\Users\hp\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe'
[pscustomobject]@{
    UserProfile = $env:USERPROFILE
    KnownFolder = [Environment]::GetFolderPath('UserProfile')
    CodexHomeIsSet = [bool]$env:CODEX_HOME
}
& $codexExe --version
& $codexExe login --help
& $codexExe login status
& $codexExe debug models --help
# Bundled metadata only; no network refresh or proof of account entitlement:
$catalog = (& $codexExe debug models --bundled | ConvertFrom-Json)
$catalog.models | Select-Object slug, display_name, visibility, supported_in_api
```

For a current catalog, the installed supported command is `debug models` without
`--bundled`. It refreshes metadata from the configured provider (and may update its
local cache), without making inference calls:

```powershell
$catalog = (& $codexExe debug models | ConvertFrom-Json)
$catalog.models | Select-Object slug, display_name, visibility, supported_in_api
```

Check whether metadata was freshly obtained or fell back to bundled/cached data.
A catalog alone still cannot prove the account can execute every entry. Obtain
non-secret account/workspace entitlement confirmation for the selected identities
and their billing route before replacing placeholders. No verification inference
is authorized here. The [CLI reference](https://learn.chatgpt.com/docs/cli/reference)
documents the distinction between bundled and refreshed catalogs.

If the normal terminal resolves the home and reports a login, the problem is
specific to the restricted process context. If it does not, investigate Windows
profile/policy resolution first. A documented process-scoped CODEX_HOME override
to an existing trusted provider home may be considered later, with approval; do
not copy auth.json, authenticate again, or change machine settings as a shortcut.

## Isolation requirements

Codex and Gemini adapters require an audited executable launcher which receives
the complete provider argv, preserves stdin/stdout/stderr and exit status, maps
schema/workspace paths if necessary, and cleans up the whole process tree. It
must expose only the empty request workspace and minimal provider authentication,
exclude benchmark/repository/user-home data and host sockets, deny model tool and
subprocess access, disable hooks/MCP/plugins/discovery and restrict outbound access
to provider endpoints. The factory checks existence, not the policy's correctness.

Installed `codex sandbox --help` exposes Windows sandbox invocation and permission
profiles. Officially supported native Windows mechanisms include MXC on compatible
devices and the legacy elevated implementation; the unelevated fallback has weaker
network isolation and cannot deny read paths. These mechanisms constrain commands
and children. They do not by themselves prove the entire provider CLI, remote
tools and credential handling satisfy this stricter launcher contract. See
[Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox) and
[agent security](https://learn.chatgpt.com/docs/agent-approvals-security).

An existing organization-audited launcher using a supported OS sandbox, or a
dedicated container/VM with a minimal filesystem and an endpoint-filtering egress
proxy, can be evaluated against that contract. Container root separation alone
does not disable tools/process creation. A container image also needs the correct
CLI and trusted auth integration; its Linux model runner cannot execute the
configured Windows .exe path. The current adapter still requires a real launcher,
not a passthrough, `wsl.exe` prefix alone, or `--sandbox read-only` alone.

No such launcher or policy has been verified. Do not fill in a pretend path.
Use an already provisioned, audited mechanism and test confinement with harmless
local probes before considering enablement. Provisioning, new sandbox accounts,
firewall rules, provider auth integration, or installing a launcher requires a
separate concrete proposal and approval. Nothing was provisioned in this task.

## Harbor, Docker, WSL and Python

Embedded Python 3.13 is available and supplies the factory's stdlib needs. The
pilot has no Harbor Python configured. Harbor is not importable in that runtime;
the optional historical user-site path is restricted. Windows PATH does not expose
Docker or Harbor. A Docker program directory exists, but no usable docker.exe was
located in that inspected directory. A read-only WSL listing initially failed in
the sandbox and succeeded with the existing approved listing permission: it lists
`docker-desktop`. Thus Docker is not claimed absent from the computer. No user
Linux distribution was listed. No WSL distribution/container was started.

Safe normal-terminal inventory and help commands:

```powershell
Get-Command docker, harbor, python, py -ErrorAction SilentlyContinue |
    Select-Object Name, Source
wsl --list --verbose
Get-ChildItem 'C:\Program Files\Docker' -Filter docker.exe -Recurse -ErrorAction SilentlyContinue |
    Select-Object FullName
py -0p
# Existing benchmark wrapper: import/version/help only, never a benchmark:
& 'F:\GITHUB\test\scripts\harbor.ps1' --version
& 'F:\GITHUB\test\scripts\harbor.ps1' --help
```

If docker.exe is discovered, use its full path for `version`, `ps`, and
`image inspect python:3.13.0-slim-bookworm`. These inspect the daemon and an existing
image; do not start Desktop, pull images, build, or run containers at this stage.
If an existing user WSL distribution is already running, inspect `command -v`
and version/help there; do not treat docker-desktop as a general Harbor Python
environment. Any discovered Harbor Python must import the actual task schema and
support the wrapper's help before selecting it in config. WSL/container paths need
an explicit, tested Windows invocation/path bridge; they cannot be inserted as
Windows Python executable paths. These integrations remain unresolved.

## Commands and approval boundary

Safe:

```powershell
& .\scripts\stem-factory.ps1 --config config/pilot.models.yaml doctor
& .\scripts\stem-factory.ps1 --config config/pilot.models.yaml run --target 1 --dry-run
```

Doctor should currently report disabled live execution and unresolved prerequisites.
Dry-run should succeed without calls or output creation.

Only after the verified identities/authentication, audited isolation, local
validation prerequisites and enforceable INR 100 cap are reviewed, the config is
deliberately enabled, and the user approves model usage, the pilot command is:

```powershell
& .\scripts\stem-factory.ps1 --config config/pilot.models.yaml run --target 1
```

Approval alone cannot make the currently disabled/unconfigured pilot ready.
No Harbor run/evaluation is part of this command or this authorization.
