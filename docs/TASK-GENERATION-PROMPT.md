# Terminal prompt: generate configured STEM tasks

Paste this into your terminal coding agent from the repository root. Set the count,
difficulty and optional tool selections in `generation.request`; the shipped
template defaults to two medium tasks with author-selected tools.

```text
Generate STEM task packages using the current generation request and configured
models/transport. Create a fresh run-specific config and output directory under task/.
Use the manifest profile: include generation.request from the current template,
retaining my requested count, difficulty, subjects and any explicit selections.
Let the author choose language, tools, dependencies and submission format where
these are auto. Keep canonical domain separate from specialization.

Use author draft → one reviewer feedback pass → author final proposal and
implementation together → packaging. Do not add a separate proposal-repair call,
second review, implementation audit or automatic rejection. Preserve reviewer
findings and mark final changes as unreviewed. Use stable requirement IDs and the
factory's canonical submission-artifact section. Preserve incomplete packages as
needs_attention drafts with diagnostics; do not claim they passed validation.

Reuse the configured accessible author/reviewer models and authentication. Run
static preflight, resolve routine configuration issues, then execute generation
using request.count (or an explicit --target override if I supplied one). Keep the
candidate limit finite and consistent with my requested number of attempts; report
shortfalls rather than starting an unbounded series of replacement candidates.

Keep existing runs intact and existing-task inventory separate from new output.
Use the installed Python interpreter. Inference containers are permitted if selected
by the existing transport. Do not execute generated commands, build task images,
run Harbor, install tools, change authentication, commit or push. Stop on account,
usage-limit or transport failures; do not repeatedly retry uncertain model requests.
If I explicitly request resuming after account access is restored, use
--retry-account-errors with the same run config. Do not silently enable it on failures.

Report task counts, models, reserved calls, absolute package paths, chosen tools,
submission artifacts, review/repair status, offline validation results, unresolved
findings and runtime checks not performed.
```

Commands after configuring a fresh run:

```console
python -m stem_factory --config config/my-run.models.yaml generate --dry-run
python -m stem_factory --config config/my-run.models.yaml generate
python -m stem_factory --config config/my-run.models.yaml report
```

`--target 5` requests five completed manifest candidates. Valid packages and
needs_attention drafts both count toward completion; only validated packages count
as accepted. Account/transport errors can still interrupt the run. No replacement
loop starts for a preserved draft.
