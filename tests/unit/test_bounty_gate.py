import tempfile
import json
from pathlib import Path
from services.bounty_gate import gate

def test_bounty_gate(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        bounty_file = Path(tmpdir) / "bounties.json"
        
        # Setup mock bounty structure
        bounties = {
            "repos": {
                "owner/eligible-repo": {"eligible": True, "tier": "Tier_1", "observed_payouts": {"high": 1000}},
                "owner/ineligible-repo": {"eligible": False, "tier": "Tier_2"},
                "prefecthq/prefect": {"eligible": True, "tier": "Tier_1"}
            },
            "formats": {
                "gguf": {"tier": "MFF_A", "bounty": 500}
            },
            "format_tiers": {
                "MFF_A": {"high": 800}
            },
            "tiers": {
                "Tier_1": {"high": 1500, "critical": 2000}
            },
            "not_eligible_confirmed": ["owner/blocked-repo"]
        }
        bounty_file.write_text(json.dumps(bounties))
        monkeypatch.setattr("services.bounty_gate.BOUNTY_FILE", bounty_file)
        
        # Test eligible repo with observed payout
        res = gate("owner/eligible-repo", "CWE-79", "high")
        assert res["decision"] == "GO"
        assert res["expected_payout"] == 1000

        # Test eligible repo using tier default
        res = gate("owner/eligible-repo", "CWE-79", "critical")
        assert res["decision"] == "GO"
        assert res["expected_payout"] == 2000

        # Test ineligible repo
        res = gate("owner/ineligible-repo", "CWE-79", "high")
        assert res["decision"] == "SKIP"

        # Test blocked repo in not_eligible_confirmed
        res = gate("owner/blocked-repo", "CWE-79", "high")
        assert res["decision"] == "SKIP"

        # Test zero override (prefecthq/prefect with CWE-94)
        res = gate("prefecthq/prefect", "CWE-94", "high")
        assert res["decision"] == "SKIP"

        # Test unknown repo
        res = gate("owner/unknown-repo", "CWE-79", "high")
        assert res["decision"] == "UNKNOWN"

        # Test format target
        res = gate("FORMAT:gguf", "CWE-79", "high")
        assert res["decision"] == "GO"
        assert res["expected_payout"] == 800
