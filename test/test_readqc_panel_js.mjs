// Pure helper functions of the short-read QC panel's page script (python/report_readqc_panel.py, HELPERS_JS), run under node.
// The Python test writes the helper source to a temporary file and calls this with its path: node test_readqc_panel_js.mjs helpers.js
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const QP = require(process.argv[2]);
let ok = true;
const check = (label, good, detail = "") => { console.log(`  ${good ? "ok  " : "FAIL"}  ${label}${good ? "" : " -> " + detail}`); ok = ok && !!good; };
const near = (a, b, e = 1e-9) => Math.abs(a - b) < e;

const s = [1, 2, 3, 4, 5];
check("quantile interpolates", near(QP.quantile(s, .5), 3) && near(QP.quantile(s, .25), 2) && near(QP.quantile(s, .1), 1.4) && QP.quantile([], .5) === null);
const b = QP.box([5, 1, 3, 2, 4, null, NaN, 100]);
check("box ignores nulls and NaN, sorts, and puts the outlier outside the whiskers", b.n === 6 && b.min === 1 && b.max === 100 && b.hi === 5 && b.lo === 1 && near(b.med, 3.5), JSON.stringify(b));
check("box of nothing is null", QP.box([]) === null && QP.box([null]) === null);
const d = QP.kde([1, 2, 3, 4, 5], 0, 6, 25);
check("kde has the requested points, is non-negative, and peaks near the middle", d.length === 25 && d.every(p => p[1] >= 0) && Math.abs(d.reduce((m, p) => p[1] > m[1] ? p : m)[0] - 3) < .6);
check("kde of one value or none does not throw", QP.kde([2], 0, 4, 10).length === 10 && QP.kde([], 0, 1, 5).length === 0);
check("csvCell quotes commas, quotes and newlines, and leaves plain text alone", QP.csvCell('a,b') === '"a,b"' && QP.csvCell('say "hi"') === '"say ""hi"""' && QP.csvCell("x\ny") === '"x\ny"' && QP.csvCell(null) === "" && QP.csvCell(3.5) === "3.5" && QP.csvCell("plain") === "plain");
check("toCsv writes a header and CRLF rows", QP.toCsv(["a", "b"], [[1, "x,y"], [2, ""]]) === 'a,b\r\n1,"x,y"\r\n2,\r\n');
check("toTsv strips tabs and newlines from cells", QP.toTsv(["a", "b"], [["x\ty", "z\nw"]]) === "a\tb\nx y\tz w\n");
check("judge: min direction", QP.judge(9, ["min", 30, 10]) === "reject" && QP.judge(25, ["min", 30, 10]) === "warn" && QP.judge(35, ["min", 30, 10]) === "pass");
check("judge: max direction, a missing reject limit never rejects", QP.judge(15, ["max", 10, null]) === "warn" && QP.judge(5, ["max", 10, null]) === "pass" && QP.judge(95, ["max", 10, 90]) === "reject");
check("judge: no value or no threshold is null", QP.judge(null, ["min", 1, 0]) === null && QP.judge(3, undefined) === null);
const t = QP.ticks(0, 100, 5);
check("ticks are round numbers inside the range", t[0] === 0 && t[t.length - 1] === 100 && t.length >= 3 && t.length <= 12, JSON.stringify(t));
check("ticks of an empty range are one value", JSON.stringify(QP.ticks(3, 3)) === "[3]");
check("move swaps neighbours, stays in range, and does not mutate", JSON.stringify(QP.move(["a", "b", "c"], 1, -1)) === '["b","a","c"]' && JSON.stringify(QP.move(["a", "b"], 0, -1)) === '["a","b"]' && JSON.stringify(QP.move(["a", "b"], 1, 1)) === '["a","b"]');
check("jitter is deterministic and within half a unit either way", QP.jitter(3) === QP.jitter(3) && [...Array(50).keys()].every(i => Math.abs(QP.jitter(i)) <= .5));
console.log();
if (!ok) { console.log("READQC PANEL JS TESTS FAILED"); process.exit(1); }
console.log("ALL READQC PANEL JS TESTS PASSED");
