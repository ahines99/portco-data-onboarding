"""Runtime evidence must distinguish measured restrictions from missing evidence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime_evidence import collect, inventory, mounts, process_status, violations


def safe_evidence():
    status = {
        "Uid": "10001 10001 10001 10001",
        "NoNewPrivs": "1",
        **dict.fromkeys(("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"), "0000000000000000"),
    }
    return {
        "application_process": status.copy(),
        "collector_process": status.copy(),
        "filesystem_inventory": {
            "suid_sgid_files": [],
            "app_ownership_or_mode_violations": [],
            "unreadable_paths": [],
        },
        "cgroup_v2_limits": {"memory.max": "2147483648", "pids.max": "256", "cpu.max": "100000 100000"},
    }


def test_runtime_profiles_do_not_attribute_compose_controls_to_image():
    evidence = safe_evidence()
    assert violations(evidence, compose=True) == []
    evidence["application_process"]["NoNewPrivs"] = "0"
    evidence["application_process"]["CapBnd"] = "0000000000000001"
    evidence["cgroup_v2_limits"]["memory.max"] = None
    assert violations(evidence) == []
    assert len(violations(evidence, compose=True)) == 3


@pytest.mark.parametrize("uids", ["0 0 0 0", "10001 0 10001 10001", "", "10001", "bad bad bad bad"])
def test_unverified_or_root_identity_cannot_pass(uids):
    evidence = safe_evidence()
    evidence["application_process"]["Uid"] = uids
    assert violations(evidence)


@pytest.mark.parametrize("field", ["suid_sgid_files", "app_ownership_or_mode_violations", "unreadable_paths"])
def test_incomplete_or_unsafe_inventory_fails(field):
    evidence = safe_evidence()
    evidence["filesystem_inventory"][field] = ["/app/unsafe"]
    assert violations(evidence)


def test_parsers_omit_unapproved_fields_mount_sources_and_options(tmp_path):
    status = tmp_path / "status"
    status.write_text("Uid:\t10001 10001 10001 10001\nToken: secret-canary\nNoNewPrivs: 1\n")
    assert process_status(status) == {"Uid": "10001 10001 10001 10001", "NoNewPrivs": "1"}
    mount = tmp_path / "mountinfo"
    mount.write_text("29 23 0:26 / /data rw,password=secret-canary - ext4 private-source rw\n")
    assert mounts(mount) == [{"mount_point": "/data", "filesystem": "ext4"}]
    assert "secret-canary" not in json.dumps([process_status(status), mounts(mount)])
    assert process_status(tmp_path / "missing") == {}


def test_inventory_detects_mutable_code_and_privileged_files(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    executable = app / "tool"
    executable.write_text("content")
    original = Path.stat

    def stat_result(path, **kwargs):
        info = original(path, **kwargs)
        if path == executable:
            return SimpleNamespace(st_mode=0o106755, st_uid=10001)
        return info

    monkeypatch.setattr(Path, "stat", stat_result)
    result = inventory((app,), app)
    assert result["suid_sgid_files"] == [str(executable)]
    assert str(executable) in result["app_ownership_or_mode_violations"]
    assert result["unreadable_paths"] == []


def test_missing_inventory_root_is_not_clean_evidence(tmp_path):
    missing = tmp_path / "missing"
    assert inventory((missing,), missing)["unreadable_paths"] == [str(missing)]


def test_collector_refuses_non_linux_host(monkeypatch):
    monkeypatch.setattr("src.runtime_evidence.platform.system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="inside the Linux container"):
        collect()
