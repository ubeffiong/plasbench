# Security policy

## Supported versions

Security fixes go into the latest release (see [CHANGELOG.md](CHANGELOG.md)). PlasBench is Alpha software; older releases are not patched.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's private reporting instead:
**Security** tab of <https://github.com/ubeffiong/plasbench> -> **Report a vulnerability**.

Include what you found, the version (`plasbench --version`), and the steps to reproduce it. You can expect an acknowledgement within 7 days and a fix or a
written assessment within 30 days.

## What is in scope

- `plasbench ui` is a local web server for one user. It listens on 127.0.0.1 only; exposing it to a network is outside its design. A way to reach it from
  another machine, or from a web page the user visits (cross-site requests), is in scope.
- Reading or writing files outside the folders a command was given (path traversal), and shell injection through a sample id, file name or sample-sheet field.
- Anything that could leak credentials (for example an NCBI key kept in `.ncbi.env`) into a log, report or released file.

## What is not

- The third-party tools PlasBench runs (MOB-suite, Platon, plasmidSPAdes and others) and their databases: report those to their authors.
- Results that are scientifically questionable. That is not a vulnerability; open an ordinary issue.
