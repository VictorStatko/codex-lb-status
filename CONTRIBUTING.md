# Contributing

Thanks for helping improve Codex LB Status.

For substantial changes, open an issue first so the intended behavior and
read-only boundary can be agreed before implementation. Keep pull requests
focused, include tests for behavior changes, and avoid adding account or server
mutation endpoints.

Follow the development setup in [README.md](README.md#development), then run:

```bash
make check
```

For changes to window, dialog, indicator, or single-instance behavior, also run
`make test-ui`.

By submitting a contribution, you agree that it is licensed under the
project's [GPL-3.0-only license](LICENSE). Do not report vulnerabilities in a
public issue; follow [SECURITY.md](SECURITY.md) instead.
