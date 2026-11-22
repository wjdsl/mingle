import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import evaluate as ev
import run_benchmark as bench


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.args = Namespace(mode="mock", phase="full", results=self.folder, max_calls=None, retry_quota=False)

    def run_jobs(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return bench.run(self.args)

    def test_design(self):
        suite, _ = bench.load_suite()
        cases = suite["cases"]
        self.assertEqual(len({c["id"] for c in cases}), 54)
        self.assertEqual(Counter(c["type"] for c in cases), {**dict.fromkeys(bench.METRICS,6), "multi":30})
        for p in ("puruma", "fridge", "cloud"):
            self.assertEqual([c["scene"] for c in cases if c["type"]=="multi" and c["project"]==p],list(range(1,11)))
        for c in cases:
            for key in ("input","expected","forbidden","criterion","character"):
                self.assertTrue(c[key])

    def test_offline_and_default(self):
        self.args.mode = "dry-run"
        with patch.object(bench, "google", side_effect=AssertionError):
            self.assertEqual(self.run_jobs(), 0)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_resume_isolation_and_evaluation(self):
        self.args.max_calls = 57  # Both models have completed four fridge turns.
        with patch.object(bench, "google", side_effect=AssertionError):
            self.assertEqual(self.run_jobs(), 2)
            self.args.max_calls = None
            self.assertEqual(self.run_jobs(), 0)
            self.assertEqual(self.run_jobs(), 0)
        folder = self.folder/"mock"
        manifest, rows = ev.read_run(folder, "full")
        self.assertEqual(len(rows),108)
        for model in bench.MODELS:
            for turn in (5, 10):
                row = next(r for r in rows if r["model"] == model and r["test_id"] == f"fridge-{turn:02}")
                contents = row["request"]["contents"]
                self.assertEqual(len(contents), 2 * turn - 1)
                for i, entry in enumerate(contents[1::2], 1):
                    self.assertEqual(entry["parts"][0]["text"], f"[MOCK] {model} fridge-{i:02}")
        ev.evaluate(folder, "full")
        file = folder/"full/reviews.json"
        reviews = json.loads(file.read_text())
        self.assertEqual(len(reviews),104)
        first = next(iter(reviews.values()))
        first["scores"]["memory"]="N/A"
        file.write_text(json.dumps(reviews))
        ev.evaluate(folder,"full")
        self.assertEqual(json.loads(file.read_text()),reviews)
        summary = json.loads((folder/"full/summary.json").read_text())
        self.assertIsNone(summary["models"][bench.MODELS[0]]["weighted"])

    def test_quota_stops_and_inflight_never_repeats(self):
        self.args.mode = "live"
        self.args.confirm_free_tier = True
        self.args.env_file = None
        with patch.object(bench,"key_from",return_value="test"), patch.object(bench,"quota_wait",return_value=None):
            with patch.object(bench,"google",return_value={"status":"error","http":429}) as post:
                self.assertEqual(self.run_jobs(),2)
                self.assertEqual(post.call_count,1)
            with patch.object(bench, "google", side_effect=AssertionError) as post:
                self.assertEqual(self.run_jobs(), 2)
                post.assert_not_called()
            with contextlib.closing(bench.open_db(self.folder / "live")) as db, db:
                db.execute("UPDATE attempts SET started = started - 86400")
            with patch.object(bench,"google",side_effect=KeyboardInterrupt) as post:
                with self.assertRaises(KeyboardInterrupt):
                    self.run_jobs()
                self.assertEqual(post.call_count,1)
            with patch.object(bench,"google",return_value={"status":"ok","response":"fake","usage":{}}) as post:
                self.args.max_calls = 1
                self.assertEqual(self.run_jobs(),2)
        _, rows = ev.read_run(self.folder/"live","full")
        self.assertEqual([r["status"] for r in rows],["error","uncertain","ok"])
        self.assertEqual(len({(r["model"],r["test_id"]) for r in rows}),3)

    def test_daily_and_token_caps_precede_dispatch(self):
        from contextlib import closing
        m = bench.MODELS[1]
        with closing(bench.open_db(self.folder)) as db:
            self.assertIn("TPM", bench.quota_wait(db, m, {"text": "a" * 250000}))
            for i in range(bench.LIMITS[m][1]):
                bench.reserve(db, "probe", m, {"id": str(i)}, {})
            self.assertIn("RPD", bench.quota_wait(db, m, {}))

    def test_non_json_quota_response_remains_a_429(self):
        with patch.object(bench.http.client, "HTTPSConnection") as conn:
            reply = conn.return_value.getresponse.return_value
            reply.status = 429
            reply.read.return_value = b"Too many requests"
            self.assertEqual(bench.google(bench.MODELS[0], "fake", {})["http"], 429)

    def test_weighted_report_after_paired_review(self):
        # Offline transport fixture in a temporary live-format journal.
        self.args.mode = "live"
        self.args.confirm_free_tier = True
        self.args.env_file = None
        with patch.object(bench, "key_from", return_value="fake"), patch.object(bench, "quota_wait"), \
             patch.object(bench, "google", return_value={"status":"ok", "response":"test", "usage":{}}) as transport:
            bench.quota_wait.return_value = None
            self.assertEqual(self.run_jobs(), 0)
            self.assertEqual(transport.call_count, 108)
        folder = self.folder / "live"
        self.assertEqual(len(json.loads((folder/"full/responses.json").read_text())["attempts"]), 108)
        ev.evaluate(folder, "full")
        path = folder / "full/reviews.json"
        forms = json.loads(path.read_text())
        for form in forms.values():
            form.update(scores=dict.fromkeys(bench.METRICS, 4), extra_violations=0, severe_violations=0)
        path.write_text(json.dumps(forms))
        ev.evaluate(folder, "full")
        for result in json.loads((folder/"full/summary.json").read_text())["models"].values():
            self.assertAlmostEqual(result["weighted"], 4.1)
            self.assertEqual(result["paired_counts"]["memory"], 52)
            self.assertEqual(result["quality_ok"], 52)
            self.assertEqual(result["automatic_violations"], 15)
        diagnostics = json.loads((folder/"full/summary.json").read_text())["fixed_reproduction"]
        for model in bench.MODELS:
            self.assertEqual(len(diagnostics[model]), 2)
            self.assertTrue(all(item["exact_match"] is False for item in diagnostics[model]))

    def test_speaker_rules_match_service_needs(self):
        suite, contexts = bench.load_suite()
        fridge = suite["cases"][0]
        cloud = next(case for case in suite["cases"] if case["project"] == "cloud")
        stored = json.loads((bench.HERE / "probe_report.json").read_text())
        for sample in stored["samples"]:
            self.assertEqual(ev.automatic(fridge, sample["response"]), [])
        self.assertEqual(ev.automatic(cloud, "모두 배로 와!"), ["speaker_format"])
        self.assertEqual(ev.automatic(cloud, "토토: 배로 와!\n비비: 엔진부터 볼게."), [])
        self.assertEqual(ev.automatic(cloud, "토토: 배로 와!\n엔진부터 볼게."), ["speaker_format"])
        self.assertEqual(ev.automatic(cloud, "토토: 배로 와!\n토토: 서둘러."), ["speaker_count"])
        self.assertIn("화자 이름을 생략하지 않는다", bench.pack(bench.make_request(cloud, contexts, [])))

    def test_partial_summary_keeps_failures_separate_and_never_double_scores(self):
        from contextlib import closing
        self.args.max_calls = 1
        self.assertEqual(self.run_jobs(), 2)
        folder = self.folder / "mock"
        with closing(bench.open_db(folder)) as db, db:
            db.execute("UPDATE attempts SET result = ?", (bench.pack({"status": "error", "http": 429}),))
            model = bench.MODELS[0]
            suite, contexts = bench.load_suite()
            case = suite["cases"][0]
            bench.reserve(db, "full", model, case, bench.make_request(case, contexts, []))
            db.execute("UPDATE attempts SET result = ? WHERE attempt = 2",
                       (bench.pack({"status": "ok", "response": "응답", "latency_s": None}),))
        ev.evaluate(folder, "full")
        summary = json.loads((folder/"full/summary.json").read_text())
        first = summary["models"][bench.MODELS[0]]
        self.assertEqual((first["attempts"], first["ok"], first["api_errors"]), (2, 1, 1))
        self.assertEqual(first["api_error_rate"], .5)
        self.assertIsNone(first["weighted"])
        self.assertIsNone(first["severe"])
        self.assertEqual(len(summary["by_test"]), 1)
        self.assertEqual(sum(ev.WEIGHTS.values()), 1.0)

    def test_full_scoring_and_bounds(self):
        import copy
        ids = ["case"]
        rows = [{"model":m,"test_id":"case","status":"ok","latency_s":4,"usage":{"promptTokenCount":12}}
                for m in bench.MODELS]
        latest = {(r["model"],"case"):r for r in rows}
        reviews = {k:{"scores":dict.fromkeys(bench.METRICS,4),"extra_violations":1,"severe_violations":1}
                   for k in latest}
        auto = {k:["speaker_count"] for k in latest}
        v = ev.summarize(bench.MODELS[0],ids,latest,rows,reviews,auto)
        self.assertEqual(v["metrics"]["efficiency"],4)
        self.assertEqual(v["violations"],2)
        self.assertEqual(v["tokens"]["output"]["total"],None)
        reviews[bench.MODELS[1],"case"]["scores"]["memory"]="N/A"
        self.assertIsNone(ev.summarize(bench.MODELS[0],ids,latest,rows,reviews,auto)["metrics"]["memory"])
        invalid=copy.deepcopy(next(iter(reviews.values())))
        invalid["scores"]["persona"] = 6
        with self.assertRaises(ValueError):
            ev.validate(invalid)
        self.assertEqual(ev.p95(list(range(1,21))),19)


if __name__ == "__main__":
    unittest.main()
