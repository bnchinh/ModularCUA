from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class SessionJournal:
    """Append-only JSONL events; payload artifacts are external and content-addressed."""

    def __init__(self, root: str | Path, episode_id: str):
        self.root = Path(root) / episode_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = self.root / "artifacts"
        self.artifact_dir.mkdir(exist_ok=True)
        self.path = self.root / "events.jsonl"
        self.event_seq = 0
        self._lock = threading.Lock()
        self.execution_mode = "CORE"
        self.raw_actor_path: Path | None = None

    def artifact(self, data: bytes, suffix: str = ".bin", media_type: str | None = None) -> dict[str, Any]:
        digest = hashlib.sha256(data).hexdigest()
        path = self.artifact_dir / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
            os.chmod(path, 0o600)
        return {"artifact_id": digest, "path": str(path), "sha256": digest,
                "size_bytes": len(data), "media_type": media_type}

    def append(self, event_type: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            self.event_seq += 1
            now = time.time()
            event = {
                "schema_version": "modularcua.event.v2",
                "event_id": str(uuid.uuid4()), "event_seq": self.event_seq,
                "episode_id": self.root.name, "event_type": event_type,
                "timestamp": now, "timestamp_utc": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.gmtime(now)
                ) + f".{int((now % 1) * 1_000_000):06d}Z",
                "execution_mode": self.execution_mode,
                **fields,
            }
            line = json.dumps(event, ensure_ascii=False, default=str)
            fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, (line + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            if self.raw_actor_path and event_type in {
                "model_request", "model_response", "tool_call", "tool_result",
                "tool_call_rejected", "agent_finish", "screenshot", "context_compaction",
            }:
                raw_fd = os.open(self.raw_actor_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                try:
                    os.write(raw_fd, (line + "\n").encode())
                    os.fsync(raw_fd)
                finally:
                    os.close(raw_fd)
        return event
