# Flexible generation: feedback then packaging

New manifest runs use exactly this sequence:

```text
Author draft → reviewer feedback → author final proposal + implementation → packaging
```

There are three model calls per candidate. A failed review never rejects the task
or starts another review. The final author receives all reviewer findings and any
initial contract/environment diagnostics, and fixes the proposal and actual files
together. No separate proposal-repair call or implementation audit is performed.

## Configuration and migration

The current template enables manifest generation with `generation.request`:

```json
{
  "count": 5,
  "difficulty": "medium",
  "language": "auto",
  "tools": "auto",
  "dependencies": "auto",
  "submission_format": "auto",
  "constraints": {
    "network_during_evaluation": false,
    "reproducible_environment": true
  }
}
```

Keep the existing subjects, model/entitlement configuration and transport. Explicit
selections are checked against the final task; `auto` lets the author choose.
Use a fresh config/output directory for this workflow. Pending cached requests from
the earlier four-call architecture have different prompt/schema identities and
must not be silently replayed. Existing task runs are not rewritten.

Manifest finalization always runs after the single review, even when older configs
have author_repairs/max_revisions set to zero. Keep these at one for clarity. These
legacy fields do not start additional manifest loops. Configs without request keep
the separate legacy Python workflow; generic task tools do not change CLI providers.
Generation still uses the configured Codex inference transport.

## One coherent final bundle

The final author returns an object with `proposal` and `implementation`. The final
proposal declares canonical domain, specialization, difficulty, tools/versions,
dependencies, image/setup plans, resource/time limits, requirements and artifacts.
The final implementation declares public instruction, starter/reference/verifier
files, command arrays, test IDs and traceability.

The factory derives requirement IDs by position in the final requirements array:
`R001`, `R002`, etc. Traceability uses these IDs; exact original sentences remain
compatible. Grouped or paraphrased labels are preserved as unresolved mappings,
with incomplete coverage recorded as warnings. Unknown test IDs also remain visible.
No semantic coverage is claimed merely because a label resembles a requirement.

Public artifact paths are rendered from output_manifest in a canonical submission
section. An instruction saying “in /work, create example.py” no longer fails because
it does not contain the single substring `/work/example.py`.

Starter files are public UTF-8 files copied into `/work`. Reference files remain
private under `/solution/files`; verifier files remain private under `/tests/private`.
Both commands run in `/work`, using declared argv arrays and explicit interpreters.
The reference creates the declared artifacts; the verifier exits zero on success.
The factory owns Dockerfiles, context separation, metadata and reward writing.

Both task images require Linux `/bin/sh` and POSIX utilities. Version declarations
and reproducibility intentions are reviewed, while missing digest/utility evidence
is recorded as runtime uncertainty. Reviewer prompts explicitly distinguish this
from a requirement to provide unavailable immutable-image evidence at authoring time.
Do not invent digests or claim that actual tools/setup have been verified.

## Outcomes without rejection

- `accepted`: the package passes offline structural checks, possibly with explicit
  warnings and unresolved reviewer findings. It is not independently approved or
  execution verified.
- `needs_attention`: incomplete/malformed content, unsafe paths, content leakage,
  failed validation, or an unrenderable environment prevents a valid package.
  The candidate and available package files are retained in `drafts/` with diagnostics.
  It is never mislabeled as rejected or offline-valid.

`--target`/request.count counts completed manifest candidates: accepted packages plus
needs_attention drafts. No replacement loop starts for preserved drafts, even with
an unlimited max_candidates setting. The report exposes completed_candidates,
accepted, needs_attention, package paths, warnings, diagnostics and runtime status.
The CLI remains nonzero if the requested number of offline-valid packages was not
reached, so downstream execution cannot mistake incomplete drafts for valid packages.

Provider authentication/quota failures, uncertain remote requests and uncertain
Docker cleanup still halt execution; the new flow does not bypass those conditions.
An invalid reviewer response is preserved as unavailable feedback and the final
author still runs. If the author response cannot be parsed, it is retained as a
draft needing attention rather than fabricating task content or starting a paid loop.

## Verification boundary

Packaging still enforces safe relative file paths, private/public separation,
content integrity, supported wrappers, coherent metadata and environment fingerprints.
Traceability wording is diagnostic rather than a rejection gate. Generated code,
image builds, tool versions, dependency availability, semantic leakage, test strength,
Oracle/NOP behavior and Harbor execution remain runtime checks. No task commands
execute on the host during generation. The legacy Python runtime validator cannot
execute general manifest packages.

Implementation: `task_spec.py` owns phase prompts and schemas, `feedback_pipeline.py`
owns the three-call lifecycle, and `manifest_package.py` renders general task files.
