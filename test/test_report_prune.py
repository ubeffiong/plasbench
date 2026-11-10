#!/usr/bin/env python3
"""
A section or tab that holds only a "Not run" notice is not shown; Run metadata lists it once, with its reason.

Hand-built page: a Summary, a Run metadata section, and
  - 'empty'    a section that holds a heading, a lead and a Not-run notice only  -> removed, listed with its reason, its id kept as an anchor;
  - 'real'     a section with a table and a Not-run sentence beside it            -> kept (it has a result);
  - 'plain'    a notice that does not start with "Not run"                        -> removed only when it says Not run somewhere; this one does not -> kept;
  - 'box'      a container whose second panel is a Not-run notice                 -> the panel and its tab button are removed, the first panel stays;
  - 'first'    a container whose FIRST panel is a Not-run notice                  -> never pruned.
A page with no Run metadata section is left as it is; running twice changes nothing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_prune as rp  # noqa: E402

PAGE = (
    "<main>"
    "<section id='summary'><h2>Summary</h2><p>s</p></section>"
    "<section id='metadata'><h2>Run metadata</h2><div class='grid'><div>x</div></div></section>"
    "<section id='empty'><h2>Copy number</h2><p class='lead'>Depth.</p><div class='insight'><p><strong>Not run:</strong> needs depth headers (RUN_X=1).</p></div></section>"
    "<section id='real'><h2>Real</h2><table><tr><th>a</th></tr></table><p>Not run: one part</p></section>"
    "<section id='plain'><h2>Plain</h2><p>Nothing to show here.</p></section>"
    "<section id='box'><h2>Box</h2><div class='rpt-mtabs'><button aria-controls='box-main'>Main</button><button aria-controls='sub'>Sub</button></div>"
    "<div class='rpt-panel' id='box-main' data-tab='Main'><p>own</p><table><tr><th>a</th></tr></table></div>"
    "<div class='rpt-panel' id='sub' data-tab='Sub'><h3>Sub</h3><p>Not run: no sub input.</p></div></section>"
    "<section id='first'><h2>First</h2><div class='rpt-mtabs'><button aria-controls='first-main'>Main</button></div>"
    "<div class='rpt-panel' id='first-main' data-tab='Main'><p>Not run: nothing.</p></div></section>"
    "</main>")


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    items = rp.pruned_items(PAGE)
    ids = [pid or sid for sid, pid, _t, _r in items]
    check("a Not-run-only section and a Not-run-only second tab are found", ids == ["empty", "sub"], ids)
    check("the reason is the text after 'Not run'", dict((pid or sid, r) for sid, pid, _t, r in items)["empty"] == "needs depth headers (RUN_X=1).")
    out = rp.prune(PAGE)
    check("the empty section is gone", "<section id='empty'" not in out)
    check("a section with a result is kept", "<section id='real'" in out)
    check("a notice without 'Not run' is kept", "<section id='plain'" in out)
    check("the second panel and its tab button are gone, the first panel stays",
          "id='sub' data-tab" not in out and "aria-controls='sub'" not in out and "id='box-main'" in out)
    check("a container's own first panel is never pruned", "id='first-main'" in out)
    check("Run metadata lists both once, with the reason and an anchor that keeps the old id landing",
          out.count("data-notrun=") == 2 and "<li id='empty' data-notrun='empty'>" in out and "needs depth headers" in out and "<li id='sub'" in out)
    check("the list is inside the Run metadata section", out.index("rpt-notrun") > out.index("id='metadata'") and out.index("rpt-notrun") < out.index("id='real'"))
    check("idempotent", rp.prune(out) == out)
    no_meta = PAGE.replace("<section id='metadata'><h2>Run metadata</h2><div class='grid'><div>x</div></div></section>", "")
    check("a page without Run metadata is left as it is", rp.prune(no_meta) == no_meta)

    print()
    if not ok:
        print("REPORT PRUNE TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT PRUNE TESTS PASSED")


if __name__ == "__main__":
    main()
