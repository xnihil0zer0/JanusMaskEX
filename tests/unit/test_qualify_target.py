import tempfile
import json
from pathlib import Path
from services.qualify_target import check_saturation, check_freshness, parse_target

def test_parse_target():
    assert parse_target("FORMAT:gguf") == ("format", "gguf")
    assert parse_target("owner/repo") == ("repo", "owner/repo")

def test_saturation(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        bounty_file = Path(tmpdir) / "bounties.json"
        
        # Setup mock bounty structure
        bounties = {
            "repos": {
                "owner/repo-sat": {"eligible": True, "submissions": 100, "tier": "A"}
            }
        }
        bounty_file.write_text(json.dumps(bounties))
        monkeypatch.setattr("services.qualify_target.BOUNTY_FILE", bounty_file)
        
        sat = check_saturation("owner/repo-sat", "repo")
        assert sat["status"] == "SKIP"
        assert sat["submissions"] == 100
