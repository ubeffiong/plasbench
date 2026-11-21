# Getting help with PlasBench

**Something failed or looks wrong?** Open a [New issue](https://github.com/ubeffiong/plasbench/issues/new/choose) and pick **Bug report**. **A question?** Pick **Question**.
**A feature idea?** Pick **Feature request**. The full guide, with a template and worked examples, is in the README section
[Reporting an issue](README.md#reporting-an-issue).

## The short version

1. **Search first**: [existing issues](https://github.com/ubeffiong/plasbench/issues?q=is%3Aissue), the [FAQ](FAQ.md) and the troubleshooting tables in the
   [README](README.md) and the [User Guide](docs/USER_GUIDE.md).
2. **One problem per issue**, with a title like `<command or page> fails with <short message> on <OS>`.
3. **Say what you did**: the exact command, or the exact buttons you clicked in order; what you expected; what happened.
4. **Paste the complete error text** from the terminal or the window's console, in a code block (not a screenshot, not a paraphrase). For long output save it with
   `plasbench <your command> 2>&1 | tee plasbench-error.log` and attach the file.
5. **Run `plasbench issue-report`** (or in the window: More > Report an issue > Prepare diagnostics). It prints one block with the PlasBench version, your computer, Docker and
   conda versions and the last lines of your run's logs, with tokens, e-mail and IP addresses and your user name already removed. `--out report.md` saves it to a file.

## Where the logs are

In your study folder (the PlasBench window's Workspace page shows it): `logs/run_*.log` (everything the run printed), `logs/<sample>.<tool>.log` (one tool on one isolate),
`results/run_events.jsonl`, `results/assembly_status.tsv`, `results/tool_status.tsv` and `results/run_manifest.json`. `plasbench status` and `plasbench diagnose` summarise a run.

## Never post

Tokens, passwords or API keys (for example the NCBI key in `.ncbi.env`), patient identifiers, private sequence data, or full read files. Check what you paste.

## Security problems

Do not open a public issue for these. Follow [SECURITY.md](SECURITY.md).
