import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import call, patch
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fetch_terms
import map as mapper


def term(number):
    return {"iri": f"http://ictv.global/id/MSL41/ICTV{number}", "label": f"Virus {number}"}


def page(number, batch, total, has_next=False):
    return {
        "_embedded": {"terms": batch},
        "page": {"number": number, "totalElements": total},
        "_links": {"next": {"href": "next"}} if has_next else {},
    }


class DownloadTests(unittest.TestCase):
    def setUp(self):
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_real_http_500_recovers_without_refetching_earlier_pages(self):
        counts = Counter()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                number = int(parse_qs(urlparse(self.path).query)["page"][0])
                counts[number] += 1
                if number == 1 and counts[number] <= 2:
                    self.send_response(500)
                    self.end_headers()
                    return
                body = json.dumps(page(number, [term(number)], 3, number < 2)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(mapper, "API_BASE", f"http://127.0.0.1:{server.server_port}"):
                with mapper.build_session(1, 0) as session:
                    terms = mapper.get_all_terms(session, "ictv", 2, page_attempts=2, page_retry_delay=0)
            self.assertEqual(terms, [term(0), term(1), term(2)])
            self.assertEqual(counts, {0: 1, 1: 3, 2: 1})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @patch.object(mapper.time, "sleep")
    def test_exhausted_retries_are_bounded_and_keep_the_failed_page(self, sleep):
        with patch.object(mapper, "request_json", side_effect=[
            page(0, [term(0)], 2, True),
            *[requests.exceptions.RetryError("too many 500 responses") for _ in range(4)],
        ]) as request:
            with self.assertRaisesRegex(RuntimeError, "page 1 failed.*download incomplete"):
                mapper.get_all_terms(None, "ictv", 30)
        self.assertEqual([c.kwargs["params"]["page"] for c in request.call_args_list], [0, 1, 1, 1, 1])
        self.assertEqual(sleep.call_args_list, [call(30.0), call(60.0), call(120.0)])

    @patch.object(mapper.time, "sleep")
    def test_connection_timeout_recovers(self, sleep):
        with patch.object(mapper, "request_json", side_effect=[requests.Timeout("slow"), page(0, [term(0)], 1)]):
            self.assertEqual(mapper.get_all_terms(None, "ictv", 30), [term(0)])
        sleep.assert_called_once_with(30.0)

    @patch.object(mapper.time, "sleep")
    def test_permanent_http_error_is_not_retried(self, sleep):
        response = requests.Response()
        response.status_code = 404
        with patch.object(mapper, "request_json", side_effect=requests.HTTPError(response=response)) as request:
            with self.assertRaises(requests.HTTPError):
                mapper.get_all_terms(None, "ictv", 30)
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_invalid_or_truncated_pages_are_never_accepted(self):
        invalid_pages = [
            {},
            [],
            page(0, [], 1),
            page(0, [term(0)], 2),
            page(0, [term(0)], 1, True),
            page(1, [term(0)], 1),
            page(0, [{"label": "Missing IRI"}], 1),
        ]
        for data in invalid_pages:
            with self.subTest(data=data), patch.object(mapper, "request_json", return_value=data):
                with self.assertRaises(RuntimeError):
                    mapper.get_all_terms(None, "ictv", 30, page_attempts=1)

    def test_changing_total_is_rejected(self):
        with patch.object(mapper, "request_json", side_effect=[
            page(0, [term(0)], 2, True), page(1, [term(1)], 3, True),
        ]):
            with self.assertRaisesRegex(RuntimeError, "page 1 failed"):
                mapper.get_all_terms(None, "ictv", 30, page_attempts=1)

    def test_duplicate_terms_across_pages_are_rejected(self):
        with patch.object(mapper, "request_json", side_effect=[
            page(0, [term(0)], 2, True), page(1, [term(0)], 2),
        ]):
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                mapper.get_all_terms(None, "ictv", 30)

    def test_invalid_retry_settings(self):
        for settings in ({"page_attempts": 0}, {"page_retry_delay": -1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                mapper.get_all_terms(None, "ictv", 30, **settings)

    @patch.object(mapper.time, "sleep")
    def test_invalid_json_is_retried(self, sleep):
        with patch.object(mapper, "request_json", side_effect=[
            requests.exceptions.JSONDecodeError("Invalid JSON", "<html>", 0),
            page(0, [term(0)], 1),
        ]):
            self.assertEqual(mapper.get_all_terms(None, "ictv", 30), [term(0)])
        sleep.assert_called_once_with(30.0)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_keeps_all_matching_fields_but_omits_unused_metadata(self):
        source = dict(term(0), synonyms=["Former name"], _links={"self": {"href": "large response"}})
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "terms.json")
            mapper.write_terms_file(path, "ictv", [source])
            loaded = mapper.load_terms_file(path)
        self.assertEqual(loaded, [dict(term(0), synonyms=["Former name"])])

    def test_snapshot_roundtrip_and_eight_shards(self):
        terms = [term(i) for i in range(19)]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "terms.json")
            mapper.write_terms_file(path, "ictv", terms)
            loaded = mapper.load_terms_file(path)
        shards = [list(mapper.shard_terms(loaded, index, 8)) for index in range(8)]
        self.assertEqual(loaded, terms)
        self.assertEqual(sorted(item for shard in shards for item in shard), list(enumerate(terms, 1)))
        self.assertEqual(len({index for shard in shards for index, _ in shard}), len(terms))
        self.assertTrue(all(shards))

    def test_corrupt_snapshots_fail_without_falling_back_to_ols(self):
        snapshots = [
            {"ontology": "ncbitaxon", "total_terms": 1, "terms": [term(0)]},
            {"ontology": "ictv", "total_terms": 2, "terms": [term(0)]},
            {"ontology": "ictv", "total_terms": 0, "terms": []},
            {"ontology": "ictv", "total_terms": 2, "terms": [term(0), term(0)]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terms.json"
            for snapshot in snapshots:
                with self.subTest(snapshot=snapshot):
                    path.write_text(json.dumps(snapshot), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        mapper.load_terms_file(str(path))

    def test_failed_write_does_not_replace_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terms.json"
            mapper.write_terms_file(str(path), "ictv", [term(0)])
            before = path.read_bytes()
            with patch.object(mapper.json, "dump", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    mapper.write_terms_file(str(path), "ictv", [term(1)])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_failed_download_does_not_publish_any_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terms.json"
            with patch.object(sys, "argv", ["fetch_terms.py", "--output", str(path)]), \
                 patch.object(fetch_terms, "get_all_terms", side_effect=RuntimeError("OLS page 1 failed")), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    fetch_terms.main()
            self.assertEqual(result.exception.code, 1)
            self.assertFalse(path.exists())

    def test_fetch_command_writes_snapshot_after_complete_download(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terms.json"
            with patch.object(sys, "argv", ["fetch_terms.py", "--output", str(path)]), \
                 patch.object(mapper, "request_json", return_value=page(0, [term(0)], 1)), \
                 contextlib.redirect_stdout(io.StringIO()):
                fetch_terms.main()
            self.assertEqual(mapper.load_terms_file(str(path)), [term(0)])

    def test_failed_download_leaves_previous_snapshot_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terms.json"
            mapper.write_terms_file(str(path), "ictv", [term(0)])
            before = path.read_bytes()
            with patch.object(sys, "argv", ["fetch_terms.py", "--output", str(path)]), \
                 patch.object(fetch_terms, "get_all_terms", side_effect=RuntimeError("500")), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    fetch_terms.main()
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
