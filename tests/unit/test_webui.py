import json
import pytest
from pathlib import Path
from webui.app import app, DB_PATH, STATE_FILE, BOUNTY_FILE, PROGRESS_FILE, ALLOWLIST_FILE, CONFIG_FILE


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_webui_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"NobleJanus" in res.data
    assert b"htmx" in res.data


def test_webui_partial_stats(client):
    res = client.get("/partial/stats")
    assert res.status_code == 200
    assert b"Confirmed Revenue" in res.data
    assert b"Current Phase" in res.data


def test_webui_partial_queue(client):
    res = client.get("/partial/queue")
    assert res.status_code == 200
    assert b"Active Workers Queue" in res.data


def test_webui_partial_grounding(client):
    res = client.get("/partial/grounding")
    assert res.status_code == 200
    assert b"Grounding" in res.data
    assert b"Target Repo" in res.data


def test_webui_partial_bounty_board(client):
    res = client.get("/partial/bounty_board")
    assert res.status_code == 200
    assert b"Bounty Target Board" in res.data


def test_webui_partial_feed(client):
    res = client.get("/partial/feed")
    assert res.status_code == 200
    assert b"Dual-Agent Live Feed" in res.data
    assert b"Fuzzing Coverage" in res.data


def test_webui_partial_activity(client):
    res = client.get("/partial/activity")
    assert res.status_code == 200
    assert b"Live Operations Feed" in res.data


def test_webui_partial_settings(client):
    res = client.get("/partial/settings")
    assert res.status_code == 200
    assert b"Auto-Promote Allowlist" in res.data
    assert b"System Configurations" in res.data


def test_webui_partial_diff_viewer(client):
    res = client.get("/partial/diff_viewer")
    assert res.status_code == 200
    assert b"Dual-Agent Live Diff-Viewer" in res.data


def test_webui_partial_fuzzing_tracker(client):
    res = client.get("/partial/fuzzing_tracker")
    assert res.status_code == 200
    assert b"Fuzzing Mutation Tracker" in res.data


def test_webui_actions(client):
    # Preview plan action
    res_preview = client.post("/action/preview_plan", data={"brief_content": "- [ ] Check crypto seed\n- [ ] Run AST"})
    assert res_preview.status_code == 200
    assert b"Check crypto seed" in res_preview.data

    # Submit brief error check
    res_brief_err = client.post("/action/submit_brief", data={"brief_name": "test_brief", "brief_content": ""})
    assert res_brief_err.status_code == 200
    assert b"cannot be empty" in res_brief_err.data


def test_action_update_config(client):
    # Live adjust system config
    res = client.post("/action/update_config", data={
        "parallel_cap": "5",
        "min_ram_mb": "1024",
        "cooldown_tier_1": "100",
        "cooldown_tier_2": "1000",
        "cooldown_tier_3": "10000"
    })
    assert res.status_code == 200
    assert b"Settings updated successfully" in res.data

    # Verify key configurations updated in config.yaml
    assert CONFIG_FILE.exists()
    import yaml
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    assert cfg["autowork"]["parallel_cap"] == 5
    assert cfg["autowork"]["min_ram_mb"] == 1024
    assert cfg["autowork"]["cooldown_tier_1"] == 100.0


def test_action_allowlist(client):
    # Clear allowlist for testing
    if ALLOWLIST_FILE.exists():
        ALLOWLIST_FILE.unlink()

    # Add a slug
    res_add = client.post("/action/allowlist/add", data={"new_slug": "test_audit_slug"})
    assert res_add.status_code == 200
    assert b"test_audit_slug" in res_add.data

    # Remove the slug
    res_remove = client.post("/action/allowlist/remove?slug=test_audit_slug")
    assert res_remove.status_code == 200
    assert b"test_audit_slug" not in res_remove.data


def test_action_kill_invalid_pid(client):
    # Check that termination of an arbitrary system PID (e.g. 1) is blocked by security validation
    res = client.post("/action/kill/1")
    assert res.status_code == 403
    assert b"not a registered worker" in res.data
