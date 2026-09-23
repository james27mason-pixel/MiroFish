"""Durable snapshot persistence for free/ephemeral Render deployments.

MiroFish writes projects, simulations and reports to Config.DATA_DIR. Render's
free filesystem is ephemeral, so this module snapshots that directory into a
private Supabase Postgres row and restores it at process start.

The database is accessed with the system `psql` client to avoid adding a Python
Postgres driver to MiroFish's locked dependency graph.
"""

from __future__ import annotations

import atexit
import base64
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.persistence")
_STATE_ID = "render-primary"
_lock = threading.Lock()
_stop = threading.Event()
_started = False


def _database_url() -> str | None:
    return os.environ.get("SUPABASE_DB_URL")


def enabled() -> bool:
    return bool(_database_url())


def _psql(sql: str, *, capture: bool = False) -> str:
    url = _database_url()
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is not configured")
    result = subprocess.run(
        ["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-t", "-A"],
        input=sql,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
        env={**os.environ, "PGCONNECT_TIMEOUT": "15"},
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "psql failed").strip())
    return result.stdout.strip() if capture else ""


def _archive_data_dir() -> str:
    root = Path(Config.DATA_DIR)
    root.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in root.rglob("*"):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(root), recursive=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _safe_extract(payload: bytes) -> None:
    root = Path(Config.DATA_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        for member in tar.getmembers():
            target = (root / member.name).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError("Unsafe path in persistence archive")
            if member.issym() or member.islnk():
                raise RuntimeError("Links are not allowed in persistence archive")
        tar.extractall(root)


def restore() -> bool:
    """Restore the latest snapshot before request handling begins."""
    if not enabled():
        logger.warning("SUPABASE_DB_URL is not set; durable persistence is disabled")
        return False
    with _lock:
        try:
            value = _psql(
                "SELECT encode(archive, 'base64') FROM public.mirofish_state_store "
                f"WHERE id = '{_STATE_ID}' LIMIT 1;",
                capture=True,
            )
            if not value:
                logger.info("No Supabase persistence snapshot exists yet")
                return False
            payload = base64.b64decode("".join(value.split()))
            _safe_extract(payload)
            logger.info("MiroFish state restored from Supabase")
            return True
        except Exception as exc:
            logger.error("Supabase restore failed: %s", exc)
            return False


def snapshot() -> bool:
    """Atomically replace the server-side snapshot."""
    if not enabled():
        return False
    with _lock:
        try:
            encoded = _archive_data_dir()
            # Base64 is a restricted alphabet; decode() in Postgres converts it
            # back to bytea without interpolating user-controlled SQL syntax.
            sql = (
                "INSERT INTO public.mirofish_state_store (id, archive, updated_at) VALUES ("
                f"'{_STATE_ID}', decode('{encoded}', 'base64'), now()) "
                "ON CONFLICT (id) DO UPDATE SET archive = EXCLUDED.archive, updated_at = now();"
            )
            _psql(sql)
            logger.debug("MiroFish state snapshot saved to Supabase")
            return True
        except Exception as exc:
            logger.error("Supabase snapshot failed: %s", exc)
            return False


def _snapshot_loop(interval: int) -> None:
    while not _stop.wait(interval):
        snapshot()


def start() -> None:
    """Restore state and start periodic durable snapshots once per process."""
    global _started
    if _started:
        return
    _started = True
    if not enabled():
        logger.warning("Durable persistence inactive; set SUPABASE_DB_URL on Render")
        return
    restore()
    interval = max(15, int(os.environ.get("MIROFISH_SNAPSHOT_INTERVAL", "30")))
    thread = threading.Thread(
        target=_snapshot_loop,
        args=(interval,),
        name="mirofish-persistence",
        daemon=True,
    )
    thread.start()
    atexit.register(snapshot)
    logger.info("Durable Supabase persistence active (%ss snapshots)", interval)
