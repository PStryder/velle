"""Tests for velle.audit — audit logging module."""

import json

from velle.audit import audit_log


class TestAuditLog:
    def test_writes_local_jsonl(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        state = {"audit_mode": "local", "session_start": "2026-01-01T00:00:00+00:00"}
        entry = {"tool": "velle_prompt", "text": "hello", "outcome": "injected"}
        audit_log(entry, state, audit_path=audit_file)

        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool"] == "velle_prompt"
        assert "timestamp" in data
        assert data["session_start"] == "2026-01-01T00:00:00+00:00"

    def test_skips_local_in_memorygate_mode(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        state = {"audit_mode": "memorygate", "session_start": None}
        entry = {"tool": "test", "outcome": "ok"}
        audit_log(entry, state, audit_path=audit_file)

        # File should not be created when mode is memorygate-only
        assert not audit_file.exists()

    def test_both_mode_writes_local(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        state = {"audit_mode": "both", "session_start": None}
        entry = {"tool": "test", "outcome": "ok"}
        audit_log(entry, state, audit_path=audit_file)

        assert audit_file.exists()
        data = json.loads(audit_file.read_text().strip())
        assert data["tool"] == "test"
