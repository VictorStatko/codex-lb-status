# Security policy

Security fixes are provided for the latest release only.

Please do not open a public issue for a suspected vulnerability. Email
<statkovit@gmail.com> with the subject `codex-lb-status security` and include
the affected version, impact, reproduction steps, and any suggested fix. Do
not include live passwords, TOTP codes, or session cookies.

Security-sensitive areas include the fixed read-only HTTP endpoint allowlist,
TLS and redirect handling, response-size and text bounds, per-origin cookie
isolation, credential lifetime, local file permissions, and single-instance
activation protocol.
