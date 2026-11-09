#!/usr/bin/env python3
"""
report_figures.py -- the figure modules of the report, injected in one place.

Each module below exposes inject(page, results_dir, data_dir, scores_path) and adds its own section(s) (ids listed in FIGURE_SECTIONS)
before Recommendations. A module that is not installed is skipped by name, so a partial checkout still builds; a module that is installed
but raises is NOT hidden: the exception propagates and fails the build, because a silent figure would look like "nothing to show".

  fig-ladder        report_fig_ladder         the reconstruction ladder: contigs, binning, ordering and orientation, reconstruction,
                                              reference validation, and which score layer judges which step
  fig-landscape     report_fig_landscape      3D scatter: accuracy, completeness and structural fidelity (an illustrative projection of metrics)
  fig-heatmap       report_fig_heatmap        tools by metrics heatmap with clustering
  fig-distributions report_fig_stats          CPRR distributions (box / violin with isolates) by tool and species
  fig-forest        report_fig_stats          forest plot of CPRR differences by species, plasmid size and reference tier
  fig-pr            report_fig_pr             interactive precision-recall plot

Standard library only.
"""
import importlib

FIGURE_MODULES = ["report_fig_ladder", "report_fig_landscape", "report_fig_heatmap", "report_fig_stats", "report_fig_pr"]
FIGURE_SECTIONS = ["fig-ladder", "fig-landscape", "fig-heatmap", "fig-distributions", "fig-forest", "fig-pr"]


def inject(page, results_dir, data_dir, scores_path):
    for name in FIGURE_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:      # a missing dependency of an installed module is a real error
                raise
            continue
        page = module.inject(page, results_dir, data_dir, scores_path)
    return page
