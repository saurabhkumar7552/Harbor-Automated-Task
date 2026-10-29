# Inspection, 2026-10-29

Requested source: `F:\GITHUB\test\tasks`; existing task: `calculate-average`.
No source task, existing benchmark model configuration, job, result or script was modified.
This session's filesystem permissions denied writes to F: and directly to the user-home
directory. Implementation was therefore created in the writable
`C:\Users\hp\AppData\Local\Temp\stem-task-factory` directory. Copy it to the intended
repository with your normal filesystem access; the factory itself does not modify
existing tasks. Keep this source outside temporary storage for long-term use.

`git -C F:\GITHUB\test rev-parse --show-toplevel` returned `E:/`, and
`--show-prefix` was empty. `F:\.git` exists; no `.git` was found at `F:\GITHUB\test`.
Status included drive-level untracked files and recycle-bin deletions. This is not a
clean dedicated benchmark checkout. No Git operation that changes state was performed.
No applicable AGENTS.md was found in the inspected source ancestors or user root.

## Existing conventions

Read task.toml, instruction, README, environment and tests Dockerfiles, solve.sh,
test.sh, Python tests, static-check and local-oracle helper, and harbor.ps1.
Schema 1.3 has top-level artifacts, org/name task name, agent/environment public
network baseline, separate no-network verifier with its own Docker image built
from tests/, scalar `/logs/verifier/reward.txt`, hidden unittest tests and an
Oracle-only shell reference. Python image: `python:3.13.0-slim-bookworm`.
Only environment/ is the public build context; hidden material stays outside it.
The factory specializes this convention to one Python submission `/work/task.py`.

## Actual installed interfaces

| Component | Observation |
| --- | --- |
| Python | `python`/`python3` absent from PATH; py launcher says no installed runtimes. Existing temporary embedded Python is 3.13.0 and works via full path. |
| Dependencies | No project pyproject/requirements files found. The old README's Harbor site-packages directory is absent; C:\Python313\Lib\site-packages has no usable packages. Factory needs only stdlib for shipped JSON-form YAML. |
| Harbor | Unavailable in inspected environments. Import/distribution lookup fails. Version/help cannot be obtained. README's historical claim of 0.20.0 is not treated as current installation evidence. Nothing installed. |
| Codex | 0.165.0 at C:\Users\hp\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe; --version, --help, exec --help and features list inspected. |
| Claude Code | 2.1.252 at C:\Users\hp\.local\bin\claude.exe; --version and full --help inspected. No --effort option was present. |
| Gemini | Not found on PATH or in inspected user npm/bin locations. Not installed or live-tested. Runtime capability probe required before use. |
| Docker | Not found on PATH or inspected common executable locations. Desktop app presence alone does not establish usable CLI/daemon. Local containers were not run. |

No models were invoked for task generation, no software was installed, no Harbor
benchmark was started. Model IDs remain explicit placeholders; access to a model
cannot be inferred from the CLI version or a ChatGPT subscription alone.

## Documentation consulted

- [Official Harbor task conventions](https://docs.harborframework.com/tasks/overview)
- [Official Gemini headless envelopes](https://geminicli.com/docs/cli/headless/)
- [Official Gemini configuration reference](https://geminicli.com/docs/reference/configuration/)
- [Official OpenAI authentication](https://learn.chatgpt.com/docs/auth)

Installed help governs Codex and Claude flags. Gemini's documented interface is
implemented defensively and remains unverified on a local installation.
