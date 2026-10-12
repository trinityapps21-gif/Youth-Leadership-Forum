"""Talk to Turso over plain HTTPS (the documented /v2/pipeline API).

Why: it uses only the Python standard library, works the same in every thread,
and every call has a time limit. A slow or unreachable database produces a
clear error after a few seconds instead of freezing the web worker.

It mimics the small part of the sqlite3 interface that db.py uses:
execute(), commit(), close(), cursor.description, fetchone(), fetchall().
Each statement runs as its own transaction (autocommit), which is how the
app already uses the database.
"""
import base64
import http.client
import json
import socket
import ssl
from urllib.parse import urlparse


class TursoError(Exception):
    pass


def _encode(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode()}
    return {"type": "text", "value": str(value)}


def _decode(cell):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


class Cursor:
    def __init__(self, result):
        cols = [c.get("name") for c in result.get("cols", [])]
        self.description = [(n, None, None, None, None, None, None) for n in cols] if cols else None
        self._rows = [tuple(_decode(c) for c in row) for row in result.get("rows", [])]
        self.rowcount = result.get("affected_row_count", -1)
        self.lastrowid = result.get("last_insert_rowid")

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class Connection:
    def __init__(self, url, auth_token, timeout=15):
        parsed = urlparse(url if "://" in url else "libsql://" + url)
        scheme = "http" if parsed.scheme == "http" else "https"  # http only for local testing
        self._host = parsed.hostname
        self._port = parsed.port or (80 if scheme == "http" else 443)
        self._secure = scheme == "https"
        self._token = auth_token
        self._timeout = timeout
        self._http = None

    # --- plumbing ---
    def _open(self):
        if self._secure:
            return http.client.HTTPSConnection(self._host, self._port, timeout=self._timeout,
                                               context=ssl.create_default_context())
        return http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)

    def _post(self, requests):
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode()
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        last = None
        for attempt in (1, 2):  # the 2nd try covers a kept-alive connection the server already closed
            try:
                if self._http is None:
                    self._http = self._open()
                self._http.request("POST", "/v2/pipeline", body=body, headers=headers)
                resp = self._http.getresponse()
                data = resp.read()
                break
            except socket.timeout:
                self._reset()
                raise TursoError(f"Turso did not answer within {self._timeout} seconds.")
            except (http.client.HTTPException, OSError) as e:
                self._reset()
                last = e
        else:
            raise TursoError(f"Could not reach Turso ({type(last).__name__}: {last}). "
                             "Check TURSO_DATABASE_URL.")
        if resp.status == 401 or resp.status == 403:
            raise TursoError("Turso rejected the auth token (HTTP %d). Create a new one with: "
                             "turso db tokens create <database-name>" % resp.status)
        if resp.status == 404:
            raise TursoError("Turso could not find that database (HTTP 404). Check TURSO_DATABASE_URL.")
        if resp.status != 200:
            raise TursoError(f"Turso returned HTTP {resp.status}: {data[:200].decode(errors='replace')}")
        try:
            return json.loads(data)["results"]
        except (ValueError, KeyError):
            raise TursoError("Turso sent a reply this app could not read: " + data[:200].decode(errors="replace"))

    def _reset(self):
        if self._http is not None:
            try:
                self._http.close()
            except Exception:
                pass
        self._http = None

    @staticmethod
    def _check(result):
        if result.get("type") != "ok":
            err = result.get("error") or {}
            raise TursoError(err.get("message") or json.dumps(result)[:300])
        return result["response"]["result"]

    # --- the small sqlite3-style surface ---
    def execute(self, sql, params=()):
        stmt = {"sql": sql, "args": [_encode(p) for p in params]}
        results = self._post([{"type": "execute", "stmt": stmt}])
        return Cursor(self._check(results[0]))

    def batch(self, statements):
        """Run many statements (no parameters) in a single round trip."""
        results = self._post([{"type": "execute", "stmt": {"sql": s}} for s in statements])
        for r in results[: len(statements)]:
            self._check(r)

    def commit(self):
        pass  # every statement is already committed

    def close(self):
        self._reset()
