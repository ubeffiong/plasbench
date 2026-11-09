#!/usr/bin/env python3
"""
report_post.py -- the post-processing steps that reshape the finished report page, in one fixed order.

Each step is a module with transform(page) -> page, run on the complete page after every section exists:

  report_condense   merge the many small tables and notes into compact, status-labelled accordions
  report_collapse   fold the tables a figure now draws into closed details

report_layout (the page shell: top bar, left rail, one view at a time, ordered analytics, print / PDF behaviour) is not in this list: it must see
the sections that report_wiring and report_surfaces add afterwards, so build_html_report.py runs it on the finished page, after report_wiring.finish
and before report_info.

(report_info, which turns notes into info popovers, runs after these, in build_html_report.py.)

A step that is not installed is skipped by name; a step that is installed but raises fails the build, because a silent
gap would look like "nothing to condense" or "no layout".

Standard library only.
"""
import importlib

STEPS = ["report_condense", "report_collapse"]


def run(page):
    for name in STEPS:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            continue
        page = module.transform(page) if hasattr(module, "transform") else module.collapse(page)
    return page
