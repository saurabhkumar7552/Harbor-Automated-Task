# Validation

Current offline validation and audit findings are recorded in
[the repository audit](REPOSITORY-AUDIT.md). The earlier 2026-10-29 delivery logs,
startup receipts and machine-specific diagnostic folders are obsolete cleanup
candidates. Their user-approved deletion is pending because automatic approval
review was unavailable on 2026-10-31. See the audit report for scope and status.

Run the offline suite from the checkout root:

```console
python -m unittest discover -s tests -t .
git diff --check
```

Tests use fixture provider responses and mocked Docker operations. Local subprocess
checks validate argument, timeout and output handling. They do not establish live
model access, dependency availability, image builds, verifier correctness or Harbor
trial success. Manifest task code and setup are not executed on the host.

The generation pipeline performs offline package checks. See
[flexible generation](FLEXIBLE-GENERATION.md) and the
[terminal prompt](TASK-GENERATION-PROMPT.md) for current operation.
