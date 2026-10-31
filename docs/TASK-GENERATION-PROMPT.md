# Terminal prompt: generate two medium STEM tasks

Paste the following into your terminal coding agent from this repository's root.
This is an operator instruction for the terminal agent, not a replacement for the
factory's internal structured-response prompts.

```text
Generate exactly two medium-difficulty STEM task packages using this checkout's
current generation workflow. Inspect repository instructions and the generation
config before taking action.

Use this architecture:
initial author proposal → one reviewer pass → one author feedback repair if needed
→ author implementation and hidden tests → offline packaging.

Configure max_revisions: 1: that means two proposal versions total, not two repairs.
Call the reviewer only once per candidate. Do not add a second review or an
implementation audit. Preserve all initial findings and label repairs as unreviewed.
A passing initial proposal can proceed directly to implementation. Keep the static
package checks enabled. Preserve packaging failure diagnostics without another loop.

Choose a stronger author model and a less expensive capable reviewer from the
models actually available to the authenticated account. Keep their exact model IDs
different. Use exactly the author role for implementer. Reuse verified access
evidence where available; do not invent entitlement confirmations from model names
or from a successful login alone. Report the chosen models before live execution.
Use the current generation-supported Codex transport; do not switch to a different
provider that the generation code cannot support.

Create a fresh run-specific config and a unique output directory under task/.
Use an existing readable task inventory, separate from the new output directory.
Resolve config paths relative to the config file. Preserve prior runs and configs.
Set live_enabled: true in this run's config: this prompt authorizes live generation
for the two requested tasks. Use a finite candidate limit of 2 for this initial run;
if either candidate fails, report the shortfall rather than starting extra candidates.

Run static preflight with:
<existing-python> -m stem_factory --config <new-config> generate --target 2 --dry-run

Resolve routine configuration errors, then execute:
<existing-python> -m stem_factory --config <new-config> generate --target 2

Use a working installed Python 3.11+ interpreter. Replace the angle-bracket entries
above with actual paths; they are placeholders. Pass --target 2 explicitly because
the CLI default is five. Do not bypass provider or isolation checks.

Preserve the configured inference transport. If it uses Docker, provider CLI
containers are permitted for author/reviewer calls. Do not build task images or
execute generated task code, Oracle/NOP checks, or Harbor benchmarks in this run.
Do not install tools, change authentication, or overwrite previous run evidence.
If authentication, entitlement, usage limits or missing transport prerequisites
block execution, stop and report the exact stage and error. Do not repeatedly retry
provider failures or automatically retry requests with uncertain completion.

At completion, run the factory report command with the same config. Report:
- requested and accepted task counts;
- exact author/reviewer model IDs and total reserved model calls;
- run directory and each accepted package's absolute path;
- initial review findings and whether a repair was performed;
- review status, offline package validation status and remaining concerns;
- Harbor execution status, which should be not_run.

Do not commit or push generated packages, logs, credentials, or local run configs.
```

For another task count, change both `--target` arguments and the candidate limit.
The candidate limit controls attempts; the target controls accepted packages.
