import pytest
from pathlib import Path
from harness import target_bootstrap as tb

def test_unauthorized_nonexistent_dir_not_created(tmp_path, monkeypatch):
    workroot = tmp_path / "workroot"
    workroot.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(workroot))

    allowlist_file = tmp_path / "allowlist.txt"
    allowlist_file.write_text("/some/other/path\n", encoding="utf-8")
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(allowlist_file))

    target = tmp_path / "never_exists"
    assert not target.exists()

    with pytest.raises(tb.BootstrapRefused):
        tb.bootstrap_target(str(target))

    assert not target.exists()

def test_authorized_dir_still_bootstraps(tmp_path, monkeypatch):
    workroot = tmp_path / "workroot"
    workroot.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(workroot))

    allowlist_file = tmp_path / "allowlist.txt"
    allowlist_file.write_text(f"{tmp_path}\n", encoding="utf-8")
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(allowlist_file))

    target = tmp_path / "ext"
    assert not target.exists()

    res = tb.bootstrap_target(str(target))
    assert res == target.resolve()
    assert (target / ".git").exists()
    assert (target / ".janusmask" / "bootstrap.json").is_file()
