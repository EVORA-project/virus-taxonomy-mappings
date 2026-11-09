import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import map as mapper
from merge_mappings import load_mappings
from sssom import Mapping


class MappingSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.snapshot = self.directory / "terms.json"
        self.existing = self.directory / "existing.tsv"
        self.output = self.directory / "shard.tsv"
        self.subject = "ictv:MSL40/ICTV20042222"
        self.label = "Mimivirus bradfordmassiliense"
        self.cached = Mapping(
            subject_id=self.subject, subject_label=self.label, predicate_id="skos:exactMatch",
            object_id="ncbitaxon:3047343", object_label=self.label,
            mapping_justification="semapv:LexicalMatching",
        )
        self.argv = [
            "map.py", "--terms-file", str(self.snapshot), "--existing", str(self.existing),
            "--output", str(self.output),
        ]
        self.term = {
            "iri": "http://ictv.global/id/MSL40/ICTV20042222", "label": self.label,
        }

    def run_mapper(self, *extra):
        with patch.object(sys, "argv", self.argv + list(extra)), contextlib.redirect_stdout(io.StringIO()):
            mapper.main()

    def test_default_reuses_existing_label_without_ols_requests(self):
        mapper.write_terms_file(str(self.snapshot), "ictv", [self.term])
        mapper.write_mappings(str(self.existing), [self.cached])
        with patch.object(mapper, "get_all_terms") as enumerate_terms, \
             patch.object(mapper, "find_exact_ncbitaxon_matches") as lookup:
            self.run_mapper("--new-only")
        enumerate_terms.assert_not_called()
        lookup.assert_not_called()
        self.assertEqual(load_mappings(self.output), [])

    def test_new_msl_keeps_multiple_matches_and_historical_mappings(self):
        new_term = dict(self.term, iri="http://ictv.global/id/MSL41/ICTV20042222")
        mapper.write_terms_file(str(self.snapshot), "ictv", [self.term, new_term])
        mapper.write_mappings(str(self.existing), [self.cached])
        matches = [
            {"iri": "http://purl.obolibrary.org/obo/NCBITaxon_3047343", "label": self.label},
            {"iri": "http://purl.obolibrary.org/obo/NCBITaxon_212035", "label": "Acanthamoeba polyphaga mimivirus", "synonyms": [self.label]},
        ]
        with patch.object(mapper, "get_all_terms") as enumerate_terms, \
             patch.object(mapper, "find_exact_ncbitaxon_matches", return_value=matches) as lookup:
            self.run_mapper()
        enumerate_terms.assert_not_called()
        self.assertEqual(lookup.call_count, 1)
        keys = {mapper.mapping_key(mapping) for mapping in load_mappings(self.output)}
        self.assertEqual(keys, {
            (self.subject, "skos:exactMatch", "ncbitaxon:3047343"),
            ("ictv:MSL41/ICTV20042222", "skos:exactMatch", "ncbitaxon:3047343"),
            ("ictv:MSL41/ICTV20042222", "skos:exactMatch", "ncbitaxon:212035"),
        })

    def test_explicit_backfill_still_rechecks_cached_labels(self):
        mapper.write_terms_file(str(self.snapshot), "ictv", [self.term])
        mapper.write_mappings(str(self.existing), [self.cached])
        with patch.object(mapper, "find_exact_ncbitaxon_matches", return_value=[]) as lookup:
            self.run_mapper("--new-only", "--recheck-existing-labels")
        self.assertEqual(lookup.call_count, 1)

    def test_ncbi_failure_remains_retryable_on_the_next_run(self):
        mapper.write_terms_file(str(self.snapshot), "ictv", [self.term])
        match = {"iri": "http://purl.obolibrary.org/obo/NCBITaxon_3047343", "label": self.label}
        with patch.object(mapper, "find_exact_ncbitaxon_matches", side_effect=[
            mapper.TransientOlsError("500"), [match],
        ]) as lookup:
            self.run_mapper("--new-only")
            self.assertEqual(load_mappings(self.output), [])
            self.run_mapper("--new-only")
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(len(load_mappings(self.output)), 1)


if __name__ == "__main__":
    unittest.main()
