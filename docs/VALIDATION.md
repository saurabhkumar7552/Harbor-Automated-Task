# Delivery validation, 2026-10-29

**48 tests passed**, with zero failures or errors, on the existing embedded
Python 3.13.0 runtime. Full output: [unittest.log](unittest.log).
Machine-readable result: [test-summary.json](test-summary.json).

## Verified

- All delivered Python sources parsed successfully; pyproject.toml parsed.
- Codex 0.165.0 and Claude Code 2.1.252 version/help inspected without model calls.
- Strict JSON parsing rejects duplicate keys, prose/fences, invalid types,
  incomplete fields, invalid verdicts and nonfinite values.
- Failed/easy/hard/incomplete reviews cannot reach implementation. Revision
  feedback is retained; revised proposals get a fresh independent review request.
- Malformed review transcripts are preserved and never treated as approval.
- A fake-model/fake-container integration reaches five accepted fixture packages
  through the full orchestration path. These fixtures are NOT independently
  verified STEM tasks; the fake validator deliberately labels its reports.
- Durable requests are cached; model-call budgets and prompt-size limits stop
  extra requests. Interrupted uncertain requests require explicit retry.
- Resume handles crashes before publication and after publication, without new
  model calls. Modified accepted packages stop recovery. Single-writer locking,
  immutable destinations and staged-content hashes are exercised.
- Hidden/public package contexts, metadata, test wrappers, reference heredocs,
  mutant validity and extra-file/leakage checks are exercised.
- Real subprocess tests verify argument-array handling, timeout termination and
  bounded output. No model-proposed code executes on the host.
- Mocked Docker tests verify offline/no-pull builds, restricted container argv,
  cleanup after timeout, two clean reference runs, empty-start rejection,
  three conceptual mutant failures, and exclusion of import/setup errors from
  evidence that a mutant was caught.
- Secret redaction and sensitive-content rejection are tested using dummy values.
- The Windows wrapper successfully performs the real five-target dry-run.
- PowerShell wrapper and installer pass syntax parsing. Installer was exercised
  only in a disposable temporary fixture: existing task preserved, second copy
  rejected before overwriting files. It was NOT executed against F:.
- Actual CLI startup checks: dry-run exits 0; report shows 0 accepted; live run
  exits 2 at placeholder model validation before making calls or creating output.
  See [startup-check.json](startup-check.json) and [dry-run.json](dry-run.json).
- [Protected task hashes](protected-task-sha256.json) record ten existing source
  files for review. The factory did not write to the existing easy task.

## Environment limitations and remaining integration checks

[Doctor output](doctor.json) records that the selected model identities are
placeholders, Codex lacks an audited isolation launcher, and the configured
Harbor environment and Docker CLI/daemon are unavailable to this session.
Gemini is unavailable in the inspected locations. No tool was installed.

Therefore the real model-generation, real independent difficulty assessments,
actual Docker builds/reference/mutant execution, and installed Harbor schema
integration have NOT been validated here. The local tests use explicit fakes for
those unavailable services; they do not imply real-container or provider success.
No Harbor benchmark, paid evaluation, push, deployment or existing-model change
occurred. **Zero live task packages were generated.**

The implementation is delivered under the user temporary directory because this
session cannot write into the requested F: project. Use the included collision-safe
manual installer from your normal terminal, or copy the reviewed files into a proper
checkout yourself. Configure actual accessible model IDs, an isolation launcher
where required, existing Harbor Python and Docker, and a locally approved image.
Then doctor and the five-task run can exercise the real integration gates. Copy
the delivered source out of temporary storage for persistent use.
