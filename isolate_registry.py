# Isolate Registry — Orange Lab Microbiology CDSS
# Durable store for every saved culture, so cumulative analytics (antibiogram)
# become possible. Same persistence pattern as the HVMS:
#   local SQLite (working copy)  +  GitHub API (durable backup/restore).
#
# Streamlit Cloud has an ephemeral filesystem — every reboot wipes local files.
# Therefore GitHub is the source of truth: we pull the .db on cold start and
# push it after every write.
#
# Pure stdlib (no Streamlit import) so it stays unit-testable. GitHub config
# (token/repo/branch) is passed in explicitly by the caller (orange_lab.py
# reads it from st.secrets).

import os
import json
import uuid
import base64
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orange_lab.registry")

SCHEMA = """
CREATE TABLE IF NOT EXISTS isolates (
    id            TEXT PRIMARY KEY,
    created_at    TEXT,
    date_in       TEXT,
    branch        TEXT,
    lab_id        TEXT,
    patient_name  TEXT,
    mobile        TEXT,
    patient_key   TEXT,
    age           INTEGER,
    sex           TEXT,
    specimen      TEXT,
    organism      TEXT,
    sir_json      TEXT,
    mechanism     TEXT,
    soft_deleted  INTEGER DEFAULT 0
);
"""

_COLUMNS = ["id", "created_at", "date_in", "branch", "lab_id", "patient_name",
           "mobile", "patient_key", "age", "sex", "specimen", "organism",
           "sir_json", "mechanism", "soft_deleted"]


class IsolateRegistry:
    def __init__(self, db_path: str = "isolates.db"):
        self.db_path = db_path

    # ── connection (new per call → thread-safe under Streamlit) ────────────
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # Migrate DBs created before patient_key existed. CREATE TABLE IF
            # NOT EXISTS is a no-op on an existing table, so the new column has
            # to be added explicitly or every read of it returns nothing and
            # M39 de-duplication silently degrades on the live database.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(isolates)")}
            if "patient_key" not in cols:
                conn.execute("ALTER TABLE isolates ADD COLUMN patient_key TEXT")
                logger.info("Registry migrated: patient_key column added.")

    # ── writes ─────────────────────────────────────────────────────────────
    @staticmethod
    def patient_key(rec: Dict[str, Any]) -> str:
        """Stable identifier for CLSI M39 first-isolate-per-patient de-duplication.

        Priority: the stored pseudonymous `patient_key` → legacy direct
        identifiers → the row UUID.

        The stored key comes first because the app no longer writes names,
        mobiles or lab IDs into this database at all (PDPL 151/2020 — the file
        is pushed to GitHub). Without this branch, de-identified rows would fall
        straight through to `id:{uuid}`, every isolate would look like a
        different patient, and the antibiogram would count a patient's four
        repeat cultures as four patients — inflating the resistance rate it
        exists to measure, which is the exact failure M39 de-duplication is for.

        The legacy branch stays so rows written before de-identification still
        de-duplicate correctly, and mixed-vintage databases keep working.
        """
        pk = str(rec.get("patient_key", "") or "").strip()
        if pk:
            return f"pk:{pk}"
        for field in ("lab_id", "mobile", "patient_name"):
            v = str(rec.get(field, "") or "").strip().lower()
            if v:
                return f"{field}:{v}"
        return f"id:{rec.get('id', '')}"

    def add_isolate(self, rec: Dict[str, Any]) -> str:
        """Insert one isolate. `sir` may be passed as a dict (auto-JSON-encoded)."""
        rid = rec.get("id") or str(uuid.uuid4())
        sir = rec.get("sir")
        if sir is not None:
            sir_json = json.dumps(sir, ensure_ascii=False)
        else:
            sir_json = rec.get("sir_json") or "{}"
        row = {
            "id":           rid,
            "created_at":   rec.get("created_at") or datetime.now().isoformat(timespec="seconds"),
            "date_in":      str(rec.get("date_in", "")),
            "branch":       rec.get("branch", ""),
            "lab_id":       rec.get("lab_id", ""),
            "patient_name": rec.get("patient_name", ""),
            "mobile":       rec.get("mobile", ""),
            "patient_key":  rec.get("patient_key", ""),
            "age":          int(rec["age"]) if str(rec.get("age", "")).strip().isdigit() else None,
            "sex":          rec.get("sex", ""),
            "specimen":     rec.get("specimen", ""),
            "organism":     rec.get("organism", ""),
            "sir_json":     sir_json,
            "mechanism":    rec.get("mechanism", ""),
            "soft_deleted": 0,
        }
        with self._conn() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO isolates ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' for _ in _COLUMNS)})",
                [row[c] for c in _COLUMNS],
            )
        logger.info("Isolate saved: %s / %s (%s)", row["organism"], row["specimen"], rid)
        return rid

    def soft_delete(self, rid: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE isolates SET soft_deleted=1 WHERE id=?", (rid,))

    # ── reads ──────────────────────────────────────────────────────────────
    def list_isolates(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        q = f"SELECT {','.join(_COLUMNS)} FROM isolates"
        if not include_deleted:
            q += " WHERE soft_deleted=0"
        q += " ORDER BY date_in DESC, created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(q).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["sir"] = json.loads(d.get("sir_json") or "{}")
            except Exception:
                d["sir"] = {}
            out.append(d)
        return out

    def count(self, include_deleted: bool = False) -> int:
        q = "SELECT COUNT(*) AS c FROM isolates"
        if not include_deleted:
            q += " WHERE soft_deleted=0"
        with self._conn() as conn:
            return int(conn.execute(q).fetchone()["c"])

    # ── GitHub persistence (Contents API) ──────────────────────────────────
    def sync_pull(self, token: str, repo: str, branch: str = "main",
                  remote_path: str = "isolates.db") -> bool:
        """Download the DB from GitHub into db_path — with a data-loss guard.

        Streamlit Cloud's filesystem is ephemeral, so on a genuine cold start
        the local DB is absent/empty and the remote correctly wins. But if a
        write succeeded locally and the follow-up push failed, a later pull
        must NOT clobber the richer local copy. Mirroring the HVMS guard, we
        refuse to overwrite whenever the local DB has strictly MORE active
        isolates than the remote one.
        """
        content, _sha = _gh_get(token, repo, remote_path, branch)
        if content is None:
            logger.info("Registry pull: no remote DB yet (fresh start).")
            return False

        # Stage the remote bytes to a temp file so we can inspect before trusting.
        tmp_path = self.db_path + ".pull.tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(content)
        except Exception as exc:
            logger.exception("Registry pull failed to write temp DB: %s", exc)
            _safe_unlink(tmp_path)
            return False

        try:
            remote_count = _db_active_count(tmp_path)
        except Exception as exc:
            logger.warning("Registry pull: remote DB unreadable (%s) — ignoring pull "
                           "to protect local data.", exc)
            _safe_unlink(tmp_path)
            return False

        local_count = None
        if os.path.exists(self.db_path):
            try:
                local_count = _db_active_count(self.db_path)
            except Exception:
                local_count = None  # unreadable/new local → let remote win

        if local_count is not None and local_count > remote_count:
            logger.warning(
                "Registry pull SKIPPED: local has %d active isolates but remote "
                "only %d — keeping local to prevent data loss.",
                local_count, remote_count,
            )
            _safe_unlink(tmp_path)
            return False

        try:
            os.replace(tmp_path, self.db_path)  # atomic adopt-remote
            logger.info("Registry pulled from GitHub (%d bytes, %d active isolates).",
                        len(content), remote_count)
            return True
        except Exception as exc:
            logger.exception("Registry pull failed to replace DB: %s", exc)
            _safe_unlink(tmp_path)
            return False

    def sync_push(self, token: str, repo: str, branch: str = "main",
                  remote_path: str = "isolates.db",
                  message: Optional[str] = None) -> bool:
        """Upload the current DB file to GitHub (create or update)."""
        try:
            with open(self.db_path, "rb") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Registry push: local DB not found.")
            return False
        _content, sha = _gh_get(token, repo, remote_path, branch)  # need sha to update
        msg = message or f"Update isolate registry {datetime.now().isoformat(timespec='seconds')}"
        ok = _gh_put(token, repo, remote_path, content, branch, sha, msg)
        if ok:
            logger.info("Registry pushed to GitHub (%d bytes).", len(content))
        return ok


# ── GitHub Contents API helpers (urllib, no external deps) ─────────────────
_GH_API = "https://api.github.com/repos/{repo}/contents/{path}"


def _db_active_count(path: str) -> int:
    """Active (non-soft-deleted) isolate count in a SQLite DB at `path`.

    Returns 0 when the file exists but has no isolates table yet (a fresh or
    empty pulled DB), so a brand-new remote never counts as "more" than local.
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='isolates'"
        ).fetchone()
        if not has_table:
            return 0
        return int(conn.execute(
            "SELECT COUNT(*) FROM isolates WHERE soft_deleted=0"
        ).fetchone()[0])
    finally:
        conn.close()


def _safe_unlink(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _gh_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "OrangeLab-CDSS",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(token: str, repo: str, path: str, branch: str):
    """Return (content_bytes, sha) or (None, None) if not found."""
    url = _GH_API.format(repo=repo, path=path) + f"?ref={branch}"
    req = urllib.request.Request(url, headers=_gh_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        b64 = data.get("content", "")
        content = base64.b64decode(b64) if b64 else b""
        return content, data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        logger.warning("GitHub GET %s failed: %s", path, e)
        return None, None
    except Exception as e:
        logger.warning("GitHub GET %s error: %s", path, e)
        return None, None


def _gh_put(token: str, repo: str, path: str, content: bytes,
            branch: str, sha: Optional[str], message: str) -> bool:
    url = _GH_API.format(repo=repo, path=path)
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=_gh_headers(token), method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        logger.error("GitHub PUT %s failed: %s %s", path, e.code, e.read().decode()[:200])
        return False
    except Exception as e:
        logger.error("GitHub PUT %s error: %s", path, e)
        return False
