#!/usr/bin/env python3
"""A user tool with several tasks and several output types: manifest parsing and validation, the derivation table, registry
rows and display names, the program interface the window uses (validate_text), the scaffold options, and the conversion of
one run's output into each task row (python/user_tool_adapter.py), including `format = auto`."""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import user_tool_adapter as uta  # noqa: E402
import user_tools as ut  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


HEAD = """[tool]
name = mt
display_name = Multi Tool
task = {task}
analysis_track = short_read
[install]
method = none
verify_command = mt --help
[run]
mode = command
command = mt {{contigs}} {{outdir}}
requires = contigs
[output]
"""


def manifest(task, output, head=HEAD):
    return head.format(task=task) + output


BOTH = "format = contig_bins, contig_labels\n[output.contig_bins]\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n" \
       "[output.contig_labels]\npath = labels.tsv\ncontig_column = contig\nlabel_column = call\nscore_column = p\n"


def problems_of(text, folder=None):
    result = ut.validate_text(text, folder)
    return result["problems"]


def status_of(text):
    return {t["task"]: t["status"] for t in ut.validate_text(text)["tasks"]}


def write(folder, text, name="plasbench-tool.ini"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes((text).encode("utf-8"))
    return folder / name


def main():
    os.environ.pop("PLASBENCH_USER_TOOLS", None)

    print("tasks: parsing and ids")
    m = ut.Manifest(ut.parse_text(manifest("classification, binning_reconstruction", BOTH)))
    check("a comma list is parsed in order; the first is the primary task", m.tasks == ["classification", "binning_reconstruction"] and m.task == "classification")
    check("a single value and the legacy alias still work", ut.Manifest(ut.parse_text(manifest("reconstruction", BOTH))).tasks == ["binning_reconstruction"])
    check("ids: the primary keeps the name, the others are <name>__<task>",
          m.task_ids() == [("mt", "classification"), ("mt__binning_reconstruction", "binning_reconstruction")], m.task_ids())
    check("ids are filesystem-safe and readable", all(re.fullmatch(r"[a-z][a-z0-9_]+", i) for i, _ in m.task_ids()))
    check("display names carry the task only when there are several",
          m.task_display("classification") == "Multi Tool (classification)" and m.task_display("binning_reconstruction") == "Multi Tool (binning)"
          and ut.Manifest(ut.parse_text(manifest("classification", BOTH))).task_display("classification") == "Multi Tool")
    problems = problems_of(manifest("classification, clasification", BOTH))
    check("an unknown task is named, with the valid ones and the comma-list hint", any("'clasification'" in p and "binning_reconstruction" in p and "comma list" in p for p in problems), problems)
    result = ut.validate_text(manifest("classification, classification", BOTH))
    check("a task listed twice is counted once, with a warning", result["ok"] and any("twice" in w for w in result["warnings"]) and len(result["tasks"]) == 1, result)
    problems = problems_of(manifest("classification", BOTH).replace("name = mt", "name = my__tool"))
    check("a name containing the reserved '__' is refused", any("'__'" in p for p in problems), problems)

    print("derivation table")
    table = [
        (["contig_bins"], "binning_reconstruction", "native"), (["contig_bins"], "classification", "derived"),
        (["contig_bins"], "sequence_reassembly", "not_possible"),
        (["contig_labels"], "classification", "native"), (["contig_labels"], "binning_reconstruction", "derived"),
        (["contig_labels"], "sequence_reassembly", "not_possible"),
        (["plasmid_fasta"], "sequence_reassembly", "native"), (["plasmid_fasta"], "classification", "not_possible"),
        (["plasmid_fasta"], "binning_reconstruction", "not_possible"),
        (["fasta_dir"], "sequence_reassembly", "native"), (["fasta_dir"], "classification", "not_possible"),
        (["fasta_dir"], "binning_reconstruction", "not_possible"),
        (["contig_bins", "plasmid_fasta"], "sequence_reassembly", "native"),
    ]
    for formats, task, expected in table:
        got = ut.derive_tasks([task], formats, [], strict=True)[0]
        check(f"strict: {'+'.join(formats)} -> {task} is {expected}", got["status"] == expected, got)
    labels_bin = ut.derive_tasks(["binning_reconstruction"], ["contig_labels"], [], strict=True)[0]["how"]
    check("labels -> binning says it is one bin per plasmid contig and NOT a real grouping", "NOT a real grouping" in labels_bin, labels_bin)
    bins_cls = ut.derive_tasks(["classification"], ["contig_bins"], [], strict=True)[0]["how"]
    check("bins -> classification says a contig in any bin is plasmid", "any bin" in bins_cls, bins_cls)
    got = ut.derive_tasks(["classification", "binning_reconstruction"], ["adapter"], ["classification"], strict=True)
    check("an adapter serves exactly the tasks in adapter_tasks", [g["status"] for g in got] == ["native", "not_possible"], got)
    check("a legacy single-format manifest keeps its old meaning: binning from a plasmid FASTA is derived, not an error",
          ut.derive_tasks(["binning_reconstruction"], ["plasmid_fasta"], [], strict=False)[0]["status"] == "derived")

    print("validation: every error says what is missing and the fix")
    p = problems_of(manifest("classification, sequence_reassembly", BOTH))
    check("a task that cannot be derived is an error for that task, with the reason and the fix",
          len(p) == 1 and "sequence_reassembly" in p[0] and "Contig tables do not contain new sequence" in p[0] and "add plasmid_fasta or fasta_dir" in p[0], p)
    p = problems_of(manifest("classification, binning_reconstruction", "format = plasmid_fasta\npath = p.fa\n"))
    check("a plasmid FASTA cannot give classification or binning in a multi-task manifest (both named)",
          len(p) == 2 and any("classification cannot be produced" in x for x in p) and any("binning_reconstruction cannot be produced" in x for x in p), p)
    p = problems_of(manifest("classification, binning_reconstruction", "format = adapter\npath = r.json\nadapter = a.py\n"))
    check("an adapter without adapter_tasks serves only the primary task; the fix names adapter_tasks",
          any("binning_reconstruction" in x and "adapter_tasks" in x for x in p), p)
    check("adapter_tasks declares which tasks the adapter writes",
          status_of(manifest("classification, binning_reconstruction", "format = adapter\npath = r.json\nadapter = a.py\nadapter_tasks = classification, binning_reconstruction\n"))
          == {"classification": "native", "binning_reconstruction": "native"})
    p = problems_of(manifest("classification", "format = adapter\npath = r.json\nadapter = a.py\nadapter_tasks = sequence_reassembly\n"))
    check("adapter_tasks may only list the tool's own tasks", any("adapter_tasks lists 'sequence_reassembly'" in x for x in p), p)
    p = problems_of(manifest("classification", "format = auto\n"))
    check("format = auto needs candidates", any("needs candidates" in x for x in p), p)
    p = problems_of(manifest("classification", "format = auto, contig_bins\ncandidates = x\n"))
    check("auto cannot be combined with other formats", any("cannot be combined" in x for x in p), p)
    p = problems_of(manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\ncandidates = x\n"))
    check("candidates only applies to auto", any("only applies to format = auto" in x for x in p), p)
    p = problems_of(manifest("binning_reconstruction", "format = contig_bins\npath = b.tsv\n[output.fasta_dir]\npath = d\n"))
    check("an [output.<format>] section for a format not listed is reported", any("not listed in [output] format" in x for x in p), p)
    p = problems_of(manifest("binning_reconstruction", "format = contig_bins\npath = b.tsv\n[output.nonsense]\npath = d\n"))
    check("an unknown output section is reported", any("[output.nonsense]" in x for x in p), p)
    p = problems_of(manifest("classification, binning_reconstruction", "format = contig_bins, contig_labels\n[output.contig_bins]\npath = b.tsv\n"
                             "[output.contig_labels]\npath = l.tsv\n"))
    check("a per-format section missing its columns is reported", any("contig_labels needs label_column or score_column" in x for x in p), p)
    p = problems_of(manifest("classification, binning_reconstruction", "format = contig_bins, contig_labels\n[output.contig_bins]\npath = b.tsv\n"
                             "[output.contig_labels]\nlabel_column = 2\n"))
    check("each listed format needs its own path", any("contig_labels needs path" in x and "[output.contig_labels]" in x for x in p), p)
    p = problems_of(manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\n[output.contig_labels]\nbogus = 1\n"))
    check("an unknown key in a per-format section is reported", any("[output.contig_labels] unknown key 'bogus'" in x for x in p), p)
    check("format = auto validates with candidates, and every task is accepted (decided per sample)",
          status_of(manifest("classification, binning_reconstruction, sequence_reassembly", "format = auto\ncandidates = a.txt, b_*.fasta\n"))
          == {"classification": "native", "binning_reconstruction": "native", "sequence_reassembly": "native"})
    check("a plain single-format [output] keeps working", ut.validate_text(manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\n"))["ok"])
    p = problems_of(manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\n").replace("[install]\nmethod = none", "[install]\nmethod = none\nurl = https://e.org/x"))
    check("source keys under another method are reported", any("only applies to method = url or local" in x for x in p), p)
    p = problems_of(manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\n").replace("mt {contigs}", "{src}/mt {contigs}"))
    check("{src} without method url/local is reported with the fix", any("{src}" in x and "method = url" in x for x in p), p)

    print("source keys")
    def with_install(install, command="{src}/mt {contigs} {outdir}"):
        return ("[tool]\nname = mt\ntask = binning_reconstruction\nanalysis_track = short_read\n[install]\n" + install + "\n[run]\nmode = command\n"
                f"command = {command}\nrequires = contigs\n[output]\nformat = contig_bins\npath = b.tsv\n")
    r = ut.validate_text(with_install("method = url\nurl = http://example.org/mt.tar.gz\nsha256 = " + "a" * 64))
    check("url: http is rejected, with the reason and the https fix", not r["ok"] and any("uses http" in x and "use https://" in x for x in r["problems"]), r)
    for scheme in ("ftp", "file", "ssh"):
        r = ut.validate_text(with_install(f"method = url\nurl = {scheme}://example.org/mt.tar.gz"))
        check(f"url: {scheme}:// is rejected", not r["ok"] and any("only https" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url"))
    check("url: method = url needs url", any("url is required" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz"))
    check("url: no sha256 is valid but warns loudly", r["ok"] and any("no sha256" in w and "tampered" in w for w in r["warnings"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz\nsha256 = " + "b" * 64))
    check("url: a pinned sha256 has no such warning, and the source summary says it is pinned",
          r["ok"] and not any("no sha256" in w for w in r["warnings"]) and r["source"]["sha256_pinned"] is True and r["source"]["kind"] == "archive", r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz\nsha256 = abc"))
    check("url: a malformed sha256 is reported", any("64 hexadecimal" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz\nsha256 = " + "b" * 64 + "\nkind = zipfile"))
    check("url: an unknown kind is reported", any("kind must be one of" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.bin\nkind = archive"))
    check("url: kind = archive on a URL that is not an archive is reported", any("does not end in" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://github.com/o/mt.git\nsha256 = " + "b" * 64))
    check("url: sha256 on a git source is reported (pin the commit with ref)", any("pin the commit with ref" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://github.com/o/mt.git"))
    check("url: a git source without ref warns, and the kind is detected", r["ok"] and r["source"]["kind"] == "git" and any("no ref" in w for w in r["warnings"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz\nsha256 = " + "b" * 64 + "\nmax_download_mb = lots"))
    check("url: max_download_mb must be a whole number", any("max_download_mb" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz\nsha256 = " + "b" * 64 + "\nbuild_command = make {nope}"))
    check("url: an unknown placeholder in build_command is reported", any("build_command" in x and "{nope}" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = local"))
    check("local: method = local needs path", any("needs path" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = local\npath = /no/such/place/anywhere\nmode = sym"))
    check("local: an unknown mode is reported", any("mode must be one of link, copy" in x for x in r["problems"]), r)
    r = ut.validate_text(with_install("method = local\npath = /no/such/place/anywhere"))
    check("local: a path that does not exist is a warning (nothing is touched during validation), and copy is the default",
          r["ok"] and any("was not found" in w for w in r["warnings"]) and r["source"]["mode"] == "copy", r)
    check("nothing was created by validating (no src/ anywhere)", not Path("/no/such/place/anywhere").exists())
    r = ut.validate_text(with_install("method = url\nurl = https://example.org/mt.tar.gz\nsha256 = " + "b" * 64, command="mt {contigs} {outdir}"))
    check("url: a command that never uses {src} warns", any("does not use {src}" in w for w in r["warnings"]), r)

    print("validate_text: the contract the window codes against")
    r = ut.validate_text(manifest("classification, binning_reconstruction", BOTH))
    check("keys: ok, problems, warnings, tasks, source, outputs", set(r) >= {"ok", "problems", "warnings", "tasks", "source", "outputs"} and r["ok"], r)
    check("each task has task, status in native|derived|not_possible, how, and its id",
          all({"task", "status", "how", "id"} <= set(t) and t["status"] in ("native", "derived", "not_possible") for t in r["tasks"])
          and [t["id"] for t in r["tasks"]] == ["mt", "mt__binning_reconstruction"], r["tasks"])
    check("outputs lists each format with its path and the tasks it serves", r["outputs"] == [{"format": "contig_bins", "path": "bins.tsv", "serves": ["classification", "binning_reconstruction"]}, {"format": "contig_labels", "path": "labels.tsv", "serves": ["classification", "binning_reconstruction"]}], r["outputs"])
    check("source: method and a plain-sentence description", r["source"]["method"] == "none" and r["source"]["description"] == ut.SOURCE_HELP["none"])
    r = ut.validate_text("this is not = an ini file [")
    check("text that is not an INI file is a problem, not an exception", r["ok"] is False and r["problems"], r)
    r = ut.validate_text("")
    check("empty text lists the required keys", not r["ok"] and any("name is required" in x for x in r["problems"]), r)
    r = ut.validate_text(manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\n").replace("name = mt", "name = platon"))
    check("a built-in name is a problem", any("built-in" in x for x in r["problems"]), r)
    check("TASKS, FORMATS, INSTALL_METHODS are the documented values",
          ut.TASKS == ("binning_reconstruction", "sequence_reassembly", "classification")
          and set(ut.FORMATS) == {"contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter", "auto"}
          and set(ut.INSTALL_METHODS) == {"conda", "pip", "script", "url", "local", "none"})
    check("TASK_HELP, FORMAT_HELP and SOURCE_HELP have one plain sentence for every value",
          set(ut.TASK_HELP) == set(ut.TASKS) and set(ut.FORMAT_HELP) == set(ut.FORMATS) and set(ut.SOURCE_HELP) == set(ut.INSTALL_METHODS)
          and all(v.endswith(".") and v.count(". ") == 0 for d in (ut.TASK_HELP, ut.FORMAT_HELP, ut.SOURCE_HELP) for v in d.values()))
    check("parse_text returns the sections", ut.parse_text("[tool]\nName = X\n") == {"tool": {"name": "X"}})

    print("registry rows and display names")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        write(base / "tools" / "mt", manifest("classification, binning_reconstruction", BOTH))
        write(base / "tools" / "solo", manifest("classification", "format = contig_labels\npath = l.tsv\nlabel_column = 2\n").replace("name = mt", "name = solo"))
        os.environ["PLASBENCH_TOOLS_PATH"] = str(base / "tools")
        ut._CACHE.clear()
        import tool_capabilities
        import tool_installer_registry as tir
        import flag_database_overlap as fdo
        import headline_design as hd
        from plasbench_common import display_tool_name
        caps = ROOT / "config" / "tool_capabilities.tsv"
        rows = tool_capabilities.read_capabilities(caps)
        check("one registry row per task: the primary keeps the name, the other is <name>__<task>",
              "mt" in rows and "mt__binning_reconstruction" in rows and "solo" in rows and "solo__classification" not in rows)
        check("each row carries its own task, and binning capability follows the task",
              rows["mt"]["evaluation_task"] == "classification" and rows["mt"]["binning_capable"] == "no"
              and rows["mt__binning_reconstruction"]["evaluation_task"] == "binning_reconstruction"
              and rows["mt__binning_reconstruction"]["binning_capable"] == "yes", {k: rows[k] for k in ("mt", "mt__binning_reconstruction")})
        check("both rows share the track", rows["mt"]["analysis_track"] == rows["mt__binning_reconstruction"]["analysis_track"] == "short_read")
        check("display names say the task for a multi-task tool, and nothing extra for a single-task tool",
              display_tool_name("mt") == "Multi Tool (classification)" and display_tool_name("mt__binning_reconstruction") == "Multi Tool (binning)"
              and display_tool_name("solo") == "Multi Tool")
        check("the installer registry stays valid with several rows per tool", tir.validate(tir.read_tsv(ROOT / "config" / "tool_installers.tsv"), tir.capability_tools(caps)) == [])
        db = {r["tool"] for r in fdo.read_rows(ROOT / "config" / "tool_database_releases.tsv")}
        check("every row has a database row (the leakage check sees each)", {"mt", "mt__binning_reconstruction"} <= db)
        design = hd.Design(capabilities=str(caps))
        check("the headline design places each row in its own task: a tool is never ranked across tasks",
              design.task_of.get("mt") == hd.TASK_CLASSIFICATION and design.task_of.get("mt__binning_reconstruction") == hd.TASK_BINNING,
              (design.task_of.get("mt"), design.task_of.get("mt__binning_reconstruction")))
        check("names: a per-task id selects its tool once", ut.enabled_names("mt__binning_reconstruction, mt") == ["mt"] and ut.enabled_names("all") == ["mt", "solo"])
        try:
            ut.enabled_names("mt__sequence_reassembly")
            unknown = ""
        except ut.ManifestError as exc:
            unknown = str(exc)
        check("an id the tool does not have is an unknown name", "mt__sequence_reassembly" in unknown, unknown)
        tool = ut.cached()["mt"]
        spec = tool.run_spec("s1", {"contigs": str(base / "c.fa"), "graph": "", "reads_1": "", "reads_2": "", "long_reads": ""}, str(base / "out"), "2") \
            if (base / "c.fa").write_text(">c\nA\n") else None
        check("run-spec for several outputs hands the converter the output folder and lists every task id",
              spec["output"] == str(base / "out") and spec["task_ids"] == "mt=classification mt__binning_reconstruction=binning_reconstruction", spec)
        record = tool.run_record()
        check("the run record has tasks, ids, source and output types",
              record["tasks"] == ["classification", "binning_reconstruction"] and record["task_ids"]["mt__binning_reconstruction"] == "binning_reconstruction"
              and record["source"]["method"] == "none" and record["output_formats"] == ["contig_bins", "contig_labels"], record)
        import write_manifest
        os.environ["USER_TOOLS"] = "all"
        records, versions = write_manifest.user_tool_records(base / "results")
        os.environ.pop("USER_TOOLS")
        check("run_manifest user_tools records tasks, source and per-row versions",
              records["mt"]["tasks"] == ["classification", "binning_reconstruction"] and "source" in records["mt"]
              and "mt__binning_reconstruction" in versions and "output_choices" in records["mt"], records["mt"])
        os.environ.pop("PLASBENCH_TOOLS_PATH")
        ut._CACHE.clear()

    print("the scaffold writes valid manifests for every option")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        n = 0
        for source in ut.SOURCES:
            for tasks in ("binning_reconstruction", "classification", "sequence_reassembly", "classification,binning_reconstruction",
                          "classification,binning_reconstruction,sequence_reassembly"):
                for fmt in ("", "auto", "contig_bins,contig_labels"):
                    if fmt == "contig_bins,contig_labels" and "sequence_reassembly" in tasks:
                        continue
                    n += 1
                    made = ut.scaffold(f"sc_{n}", home, tasks, source, "https://example.org/t.tar.gz" if source == "url" else "",
                                       "a" * 64 if source == "url" else "", "~/tools/t" if source == "local" else "", fmt)
                    r = ut.validate_text(made.read_text(encoding="utf-8"), made.parent)
                    if not r["ok"]:
                        check(f"scaffold --source {source} --task {tasks} --output-format {fmt or '(default)'} is valid", False, r["problems"])
        check(f"{n} scaffold combinations (source x tasks x output format) all validate", not [f for f in FAILED if f.startswith("scaffold")])
        text = (ut.scaffold("sc_url", home, "classification", "url", "https://example.org/t.zip", "c" * 64).read_text(encoding="utf-8"))
        check("the url template explains https-only, sha256, kind, ref and {src} inline",
              "https ONLY" in text and "sha256 pins" in text and "kind = archive" in text and "ref = v1.2.0" in text and "{src}" in text)
        text = ut.scaffold("sc_multi", home, "classification,binning_reconstruction", "installed", output_format="contig_bins,contig_labels").read_text(encoding="utf-8")
        check("the multi-task template explains the comma list and has one section per output format",
              "task = classification, binning_reconstruction" in text and "[output.contig_bins]" in text and "[output.contig_labels]" in text and "ONCE per sample" in text)
        for kwargs, word in (({"tasks": "bogus"}, "task 'bogus'"), ({"source": "ftp"}, "source 'ftp'"), ({"source": "url", "url": "http://x.org/a.zip"}, "http"),
                             ({"output_format": "auto,contig_bins"}, "auto cannot"), ({"output_format": "nope"}, "output format 'nope'")):
            try:
                ut.scaffold("sc_bad", home, **kwargs)
                got = ""
            except ut.ManifestError as exc:
                got = str(exc)
            check(f"scaffold refuses {list(kwargs)[0]}", word in got, got)

    print("converting one run's output for each task")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        contigs = base / "contigs.fasta"
        contigs.write_text(">c1\nACGTACGTAC\n>c2\nGGGGCCCCAA\n>c3\nTTTTAAAAGG\n>c4\nCCCCCCCCCC\n", encoding="utf-8")
        out = base / "out"
        out.mkdir()
        (out / "bins.tsv").write_text("contig\tbin\nc1\tB1\nc2\tB1\n", encoding="utf-8")
        (out / "labels.tsv").write_text("contig\tcall\tp\nc1\tplasmid\t0.9\nc2\tchromosome\t0.2\nc3\tplasmid\t0.7\nc4\tchromosome\t0.1\n", encoding="utf-8")

        def tool_from(text, name="mt"):
            return ut.UserTool(write(base / "m" / name, text.replace("name = mt", f"name = {name}")))

        def run(tool, tid, task, outdir=out, sample="s1"):
            fasta = base / "res" / f"pred_{tid}.plasmid.fasta"
            fasta.parent.mkdir(exist_ok=True)
            target = outdir if tool.multi_output else Path(outdir) / tool.output_get(tool.formats[0], "path")
            prov = uta.convert(tool, str(target), str(contigs), str(fasta), task, tid, sample)
            stem = str(fasta)[:-len(".plasmid.fasta")]
            names = [l[1:].strip() for l in fasta.read_text().splitlines() if l.startswith(">")]
            return prov, names, Path(stem + ".bins.tsv"), Path(stem + ".scores.tsv")

        both = tool_from(manifest("classification, binning_reconstruction", BOTH))
        prov, names, bins, scores = run(both, "mt", "classification")
        check("classification <- contig_labels: the plasmid call with the PR-curve scores, no bins",
              prov["chosen_format"] == "contig_labels" and names == ["c1", "c3"] and scores.is_file() and not bins.exists(), prov)
        prov, names, bins, scores = run(both, "mt__binning_reconstruction", "binning_reconstruction")
        check("binning <- contig_bins: the real bins (the same single run's output)",
              prov["chosen_format"] == "contig_bins" and names == ["c1", "c2"] and bins.read_text().split() == ["bin_id", "sequence_id", "B1", "c1", "B1", "c2"], (prov, names))
        check("the choice is in the provenance (chosen format and path, candidates seen)", prov["chosen_path"] == "bins.tsv" and prov["task"] == "binning_reconstruction"
              and prov["id"] == "mt__binning_reconstruction" and prov["candidates_seen"], prov)

        only_bins = tool_from(manifest("classification, binning_reconstruction", "format = contig_bins\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n"), "ob")
        prov, names, bins, scores = run(only_bins, "ob", "classification")
        check("bins -> classification: every contig in a bin is plasmid; no bins file and no scores for the classifier row",
              names == ["c1", "c2"] and not bins.exists() and not scores.exists() and "any bin" in prov["derived"], (names, prov))
        only_labels = tool_from(manifest("classification, binning_reconstruction", "format = contig_labels\npath = labels.tsv\ncontig_column = contig\nlabel_column = call\nscore_column = p\n"), "ol")
        prov, names, bins, scores = run(only_labels, "ol__binning_reconstruction", "binning_reconstruction")
        check("labels -> binning: one bin per plasmid contig, flagged as not a real grouping in the provenance",
              names == ["c1", "c3"] and bins.read_text().split() == ["bin_id", "sequence_id", "c1", "c1", "c3", "c3"] and "not a real grouping" in prov["bins_flagged"], prov)

        fallback = tool_from(manifest("classification, binning_reconstruction", BOTH), "fb")
        fb_out = base / "fb_out"
        fb_out.mkdir()
        (fb_out / "labels.tsv").write_text((out / "labels.tsv").read_text(), encoding="utf-8")
        prov, names, bins, _ = run(fallback, "fb__binning_reconstruction", "binning_reconstruction", fb_out)
        check("several declared formats: when the preferred output was not written the next serves the task, and the provenance says which",
              prov["chosen_format"] == "contig_labels" and "bins_flagged" in prov, prov)
        try:
            run(fallback, "fb", "classification", base)
            gone = ""
        except uta.OutputError as exc:
            gone = str(exc)
        check("none of the declared outputs written: an error listing each path looked for", "contig_labels:" in gone and "contig_bins:" in gone, gone)

        print("format = auto")
        auto = tool_from(manifest("binning_reconstruction, classification, sequence_reassembly", "format = auto\ncandidates = contig_report.txt, plasmid_*.fasta\n"), "au")
        arun = base / "arun"
        arun.mkdir()
        (arun / "contig_report.txt").write_text(
            "sample_id\tmolecule_type\tprimary_cluster_id\tcontig_id\tsize\nS\tchromosome\t-\tc1\t10\nS\tplasmid\tAA1\tc2\t10\nS\tplasmid\tAA1\tc3\t10\nS\tchromosome\t-\tc4\t10\n", encoding="utf-8")
        (arun / "plasmid_AA1.fasta").write_text(">c2\nGGGGCCCCAA\n", encoding="utf-8")
        (arun / "plasmid_AA2.fasta").write_text(">x\nACGT\n", encoding="utf-8")
        prov, names, bins, scores = run(auto, "au", "binning_reconstruction", arun)
        check("auto: binning <- the contig report's cluster column; '-' (no bin) contigs are left out",
              prov["chosen_format"] == "contig_bins" and names == ["c2", "c3"] and "AA1\tc2" in bins.read_text() and "c1" not in bins.read_text().split(), (prov, names))
        prov, names, bins, scores = run(auto, "au__classification", "classification", arun)
        check("auto: classification <- the molecule_type label column", prov["chosen_format"] == "contig_labels" and names == ["c2", "c3"] and not bins.exists(), (prov, names))
        prov, names, bins, scores = run(auto, "au__sequence_reassembly", "sequence_reassembly", arun)
        check("auto: reassembly <- the FASTA files the pattern matched, one bin per file",
              prov["chosen_format"] == "fasta_dir" and len(names) == 2 and "plasmid_AA1" in bins.read_text(), (prov, names))
        check("auto: the provenance lists every candidate with what was seen", len(prov["candidates_seen"]) == 2 and all(c["why"] for c in prov["candidates_seen"]), prov["candidates_seen"])
        only_tables = base / "tables_only"
        only_tables.mkdir()
        (only_tables / "contig_report.txt").write_text((arun / "contig_report.txt").read_text(), encoding="utf-8")
        try:
            run(auto, "au__sequence_reassembly", "sequence_reassembly", only_tables)
            err = ""
        except uta.OutputError as exc:
            err = str(exc)
        check("auto: reassembly with only tables is an error listing what was seen (that row is skipped, the others still convert)",
              "sequence_reassembly" in err and "contig_report.txt" in err and "no file matches 'plasmid_*.fasta'" in err, err)
        prov, names, *_ = run(auto, "au", "binning_reconstruction", only_tables)
        check("... and the binning row of the same run still converts", names == ["c2", "c3"])
        amb = base / "amb"
        amb.mkdir()
        (amb / "contig_report.txt").write_text((arun / "contig_report.txt").read_text(), encoding="utf-8")
        (amb / "second.tsv").write_text("contig_id\tcluster\nc1\tX\nc2\tY\n", encoding="utf-8")
        ambiguous = tool_from(manifest("binning_reconstruction", "format = auto\ncandidates = contig_report.txt, second.tsv\n"), "am")
        try:
            run(ambiguous, "am", "binning_reconstruction", amb)
            err = ""
        except uta.OutputError as exc:
            err = str(exc)
        check("auto: two candidates that could both be the bins is an error naming both, never a silent guess",
              "contig_report.txt" in err and "second.tsv" in err and "Narrow" in err, err)
        junk = base / "junk"
        junk.mkdir()
        (junk / "notes.txt").write_text("finished\n", encoding="utf-8")
        nothing = tool_from(manifest("classification", "format = auto\ncandidates = notes.txt, missing.csv\n"), "no")
        try:
            run(nothing, "no", "classification", junk)
            err = ""
        except uta.OutputError as exc:
            err = str(exc)
        check("auto: nothing recognisable lists each candidate and what was seen", "notes.txt" in err and "finished" in err and "missing.csv" in err, err)
        hint = tool_from(manifest("binning_reconstruction", "format = auto\ncandidates = rep.txt\n[output.contig_bins]\nbin_column = molecule_type\n"), "hi")
        (arun / "rep.txt").write_text((arun / "contig_report.txt").read_text(), encoding="utf-8")
        prov, names, *_ = run(hint, "hi", "binning_reconstruction", arun)
        check("auto: an [output.<format>] hint wins over detection", prov["chosen_format"] == "contig_bins" and "chromosome" in Path(str(base / "res" / "pred_hi.bins.tsv")).read_text(), prov)

        print("adapter: called once per task")
        script = base / "m" / "ad" / "adapt.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("import os, sys\nout = sys.argv[3]\nopen(out, 'w').write('>c1\\nACGTACGTAC\\n')\n"
                          "open(out[:-len('.plasmid.fasta')] + '.task.txt', 'w').write(os.environ['PLASBENCH_TASK'])\n", encoding="utf-8")
        adapt = tool_from(manifest("classification, binning_reconstruction", "format = adapter\npath = r.json\nadapter = adapt.py\nadapter_tasks = classification, binning_reconstruction\n"), "ad")
        (out / "r.json").write_text("{}", encoding="utf-8")
        for tid, task in (("ad", "classification"), ("ad__binning_reconstruction", "binning_reconstruction")):
            run(adapt, tid, task)
            check(f"adapter row {tid}: PLASBENCH_TASK={task}", (base / "res" / f"pred_{tid}.task.txt").read_text() == task)

        print("the converter's command line")
        fasta = base / "res" / "pred_mt__binning_reconstruction.plasmid.fasta"
        orig_discover = ut.discover
        ut.discover = lambda *a, **k: {"mt": both}
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                code = uta.main(["--tool", "mt__binning_reconstruction", "--output", str(out), "--contigs", str(contigs), "--out-fasta", str(fasta), "--sample", "s1"])
            wrong = uta.main(["--tool", "nosuch", "--output", str(out), "--contigs", str(contigs), "--out-fasta", str(fasta)])
        finally:
            ut.discover = orig_discover
        provenance = json.loads((base / "res" / "pred_mt__binning_reconstruction.mt__binning_reconstruction.provenance.json").read_text())
        check("main: an id selects the task, the provenance file is named by the id, one summary line is printed for tool_status",
              code == 0 and wrong == 2 and provenance["task"] == "binning_reconstruction" and "binning_reconstruction <- contig_bins" in buffer.getvalue(), buffer.getvalue())

    if FAILED:
        print("USER TOOL MULTI-TASK TESTS FAILED")
        return 1
    print("ALL USER TOOL MULTI-TASK TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
