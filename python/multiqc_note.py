#!/usr/bin/env python3
"""The one plain-language note on MultiQC versus PlasBench's own QC panel, shared by every place that shows it.

PlasBench does not use MultiQC to make its QC panel: the panel (python/report_readqc_panel.py) is PlasBench's own, modelled on MultiQC's layout. Real MultiQC
is an optional companion (MULTIQC_REPORT, python/run_multiqc.py, `plasbench install-tools multiqc`). The same text is shown in the report's QC panel (and its
PDF), as the help for the MULTIQC_REPORT setting and in the window's report and QC help (plasbench/ui_help.py), so the wording cannot drift. Standard library only.
"""

TITLE = "MultiQC or the built-in panel? What to know"
INSTALL_COMMAND = "plasbench install-tools multiqc"

POINTS = (
    ("The built-in panel (this page)",
     "It is PlasBench's own, modelled on MultiQC's layout. It applies PlasBench's thresholds and gives every sample PASS, WARN or REJECT with the reason, "
     "shows how each assembly was selected, and answers the reviewer's questions. It works offline in this one file. It shows only the metrics PlasBench "
     "computes itself: read pairs, depth, mean Phred, Q30, read length, GC, adapters, duplication, N and read-pair synchrony."),
    ("MultiQC (optional)",
     "MultiQC is the community-standard view of the same fastp output (and QUAST output, when that was run). It draws more of it: per-base quality, "
     "adapter content, duplication curves and more. It needs a separate install (" + INSTALL_COMMAND + "), it is a separate file next to this report, and it knows "
     "nothing of PlasBench's thresholds or decisions: it describes, it does not decide."),
    ("Do they agree?",
     "Both read the same underlying files, so a figure both show should agree closely. The panel measures the first read pairs of the raw files, while fastp "
     "reports on every read it processed, before and after trimming, so small differences are expected. If they differ a lot, first check that both were made "
     "from the same files (the same run and sample), then look at the files themselves: results/short_read_qc.tsv for the panel, and the sample's fastp.json "
     "for MultiQC. The files are the record; neither picture is."),
)


def text():
    """The note as plain text (for tooltips and help)."""
    return " ".join(f"{head}: {body}" for head, body in POINTS)
