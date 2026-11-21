"""Local Salesforce query fixture.

Speaks the REST query response shape (`totalSize`, `done`, `nextRecordsUrl`,
`records`). It binds to 127.0.0.1 only. It has no credentials and it does not
call Salesforce.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

_QUERY = "/services/data/v59.0/query"


def opportunity(
    *,
    external_id: str,
    company: str,
    amount: int,
    stage: str,
    close_date: str,
    currency: str,
    modified: str,
) -> dict:
    return {
        "attributes": {
            "type": "Opportunity",
            "url": f"/services/data/v59.0/sobjects/Opportunity/{external_id}",
        },
        "Id": external_id,
        "Name": company,
        "Amount": amount,
        "StageName": stage,
        "CloseDate": close_date,
        "CurrencyIsoCode": currency,
        "Account": {"attributes": {"type": "Account"}, "Name": company},
        "LastModifiedDate": modified,
    }


class PipelineFixture:
    """Pages of Opportunity records. `fail_paths` maps a path to an HTTP status."""

    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.fail_paths: dict[str, int] = {}
        self.forced_next: str | None = None
        self.calls: list[str] = []
        self.url = ""
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                fixture.calls.append(self.path)
                status, body = fixture.response(urlsplit(self.path).path)
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, fmt: str, *args) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._httpd.server_address[:2]
        self.url = f"http://{host}:{port}"
        return self.url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> PipelineFixture:
        self.start()
        return self

    def __exit__(self, *exc) -> bool:
        self.stop()
        return False

    def response(self, path: str) -> tuple[int, dict]:
        if path in self.fail_paths:
            return self.fail_paths[path], {"message": "fixture failure"}
        index = self._index(path)
        if index is None or index < 0 or index >= len(self.pages):
            return 404, {"message": "fixture page missing"}
        records = self.pages[index]
        last = index + 1 >= len(self.pages)
        body: dict = {
            "totalSize": sum(len(page) for page in self.pages),
            "done": last,
            "records": records,
        }
        if index == 0 and self.forced_next:
            body["done"] = False
            body["nextRecordsUrl"] = self.forced_next
            body["totalSize"] = max(body["totalSize"], len(records) + 1)
        elif not last:
            body["nextRecordsUrl"] = f"{_QUERY}/fixture-page-{index + 2}"
        return 200, body

    def _index(self, path: str) -> int | None:
        if path == _QUERY:
            return 0
        prefix = f"{_QUERY}/fixture-page-"
        if path.startswith(prefix) and path[len(prefix) :].isdigit():
            return int(path[len(prefix) :]) - 1
        return None
