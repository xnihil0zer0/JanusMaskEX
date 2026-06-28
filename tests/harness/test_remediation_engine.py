import unittest
import os
import json
import tempfile
from pathlib import Path
from harness.remediation_engine import RemediationEngine

class TestRemediationEngine(unittest.TestCase):
    def test_remediate_physics_dt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RemediationEngine(target_dir=tmpdir)
            critique = {
                "accept": False,
                "reject": True,
                "reason": "The ragdoll's tail segment clipped through the floor.",
                "bugs": [
                    {
                        "id": "BUG-001",
                        "description": "Tail segment clips through floor partition.",
                        "reproduction_suggestion": "Decrease physics_dt to 0.008s to improve collision solver accuracy."
                    }
                ]
            }
            applied = engine.parse_critique_and_apply(critique)
            self.assertTrue(applied)
            
            # Read back config
            config_file = Path(tmpdir) / "drizzlet_config.json"
            self.assertTrue(config_file.exists())
            with open(config_file, "r") as f:
                data = json.load(f)
            self.assertEqual(data["physics_dt"], 0.008)

    def test_remediate_pd_gains(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RemediationEngine(target_dir=tmpdir)
            critique = {
                "accept": False,
                "reject": True,
                "reason": "gains too low",
                "bugs": [
                    {
                        "id": "BUG-002",
                        "description": "increase active ragdoll pd gains",
                        "reproduction_suggestion": "try Kp tuning"
                    }
                ]
            }
            applied = engine.parse_critique_and_apply(critique)
            self.assertTrue(applied)
            
            config_file = Path(tmpdir) / "drizzlet_config.json"
            self.assertTrue(config_file.exists())
            with open(config_file, "r") as f:
                data = json.load(f)
            self.assertEqual(data["kp_max"], 150.0 * 1.5)
            self.assertEqual(data["kd"], 2.0 * 1.2)

    def test_no_remediate_on_accept(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RemediationEngine(target_dir=tmpdir)
            critique = {
                "accept": True,
                "reject": False,
                "reason": "looks perfect",
                "bugs": []
            }
            applied = engine.parse_critique_and_apply(critique)
            self.assertFalse(applied)
            config_file = Path(tmpdir) / "drizzlet_config.json"
            self.assertFalse(config_file.exists())

if __name__ == '__main__':
    unittest.main()
