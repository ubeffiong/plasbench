# Sources of docs/IMPLEMENTATION_CATALOGUE.md

`docs/IMPLEMENTATION_CATALOGUE.md` is generated. Edit the parts here, then run `python python/build_implementation_catalogue.py`.

- `head.md`, `capabilities.md`, `tail.md`: the hand-written sections (sections 1 to 4 and 10 to 12).
- `history.tsv`: merged pull requests (number, date, title). Refresh it with `python python/build_implementation_catalogue.py --refresh-history` (needs the GitHub CLI, `gh`).
- Sections 5 to 9 (tools, modules, outputs, switches, history) are built from the repository itself.
