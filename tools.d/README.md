# User tools

Put one folder per tool here (`tools.d/<name>/plasbench-tool.ini`), in `~/.plasbench/tools/`, or in a folder named
by `$PLASBENCH_TOOLS_PATH`. PlasBench then installs, runs, scores and reports it like a built-in tool:

```bash
plasbench tools new my_tool            # writes a commented manifest to fill in
plasbench tools validate my_tool       # lists every problem, with the fix
plasbench install-tools my_tool        # from its [install] section, into its own environment
plasbench run --tool my_tool ...       # benchmark it beside the built-in tools
```

`examples/` holds one worked manifest per output format. They are templates: folders below `examples/` are not on
the search path and never run. Copy one (`plasbench tools add tools.d/examples/example_contig_bins`) and edit it.
The full reference is [docs/ADDING_TOOLS.md](../docs/ADDING_TOOLS.md).
