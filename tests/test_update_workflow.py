import unittest
from pathlib import Path

import yaml


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/update-mappings.yml"
        with path.open(encoding="utf-8") as file:
            cls.workflow = yaml.load(file, Loader=yaml.BaseLoader)

    def test_matching_still_uses_eight_shards_and_two_parallel_jobs(self):
        job = self.workflow["jobs"]["generate-shards"]
        self.assertEqual(job["strategy"]["matrix"]["shard"], [str(i) for i in range(8)])
        self.assertEqual(job["env"]["SHARD_COUNT"], "8")
        self.assertEqual(job["strategy"]["max-parallel"], "2")
        self.assertEqual(job["strategy"]["fail-fast"], "false")

    def test_shards_require_a_complete_snapshot_and_merge_requires_shards(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(jobs["generate-shards"]["needs"], "prepare-ictv-terms")
        self.assertEqual(jobs["merge-mappings"]["needs"], "generate-shards")
        self.assertEqual(jobs["prepare-ictv-terms"]["timeout-minutes"], "30")
        producer = next(step for step in jobs["prepare-ictv-terms"]["steps"] if step["name"] == "Upload ICTV term snapshot")
        consumer = next(step for step in jobs["generate-shards"]["steps"] if step["name"] == "Download ICTV term snapshot")
        self.assertEqual(producer["with"]["name"], consumer["with"]["name"])
        self.assertEqual(producer["with"]["if-no-files-found"], "error")
        generate = next(step["run"] for step in jobs["generate-shards"]["steps"] if step["name"] == "Generate shard")
        snapshot = str(Path(consumer["with"]["path"]) / "ictv-terms.json")
        self.assertEqual(producer["with"]["path"], snapshot)
        self.assertIn(f"--terms-file {snapshot}", generate)
        self.assertIn("--existing mappings/ictv_ncbitaxon_exact.sssom.tsv", generate)
        self.assertIn("--new-only", generate)

    def test_backfill_is_still_opt_in_and_logs_are_unbuffered(self):
        option = self.workflow["on"]["workflow_dispatch"]["inputs"]["recheck_existing_labels"]
        self.assertEqual(option["default"], "false")
        self.assertEqual(self.workflow["env"]["PYTHONUNBUFFERED"], "1")


if __name__ == "__main__":
    unittest.main()
