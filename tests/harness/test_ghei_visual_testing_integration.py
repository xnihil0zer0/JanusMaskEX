import unittest
import os
import json
import tempfile
import socket
import time
import urllib.request
import pygame
from pathlib import Path
from harness.visual_prompt_generator import OptimizedVisualPromptGenerator, parse_json_response
from harness.remediation_engine import RemediationEngine
from drizzlet.drizzlet_api import start_api_server

class TestGHEIVisualTestingIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        # Initialize display headlessly
        try:
            pygame.display.set_mode((1, 1), pygame.NOFRAME)
        except Exception:
            pass
        
        # Find a free port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        cls.port = s.getsockname()[1]
        s.close()
        
        cls.server, cls.shared_state = start_api_server(port=cls.port)
        time.sleep(0.3)

    def test_prompt_generator_with_relevancy(self):
        doc_content = """# Section 1: Myxophage Viscoplastic rolling
The Myxophage viscoplastic rolling is simulated using Herschel-Bulkley.

# Section 2: Combat permittivity HUD
coronal sparks indicate relative permittivity wetness.
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(doc_content)
            temp_path = f.name
            
        try:
            generator = OptimizedVisualPromptGenerator(temp_path)
            spec = generator.extract_relevant_spec("Check Myxophage rolling")
            self.assertIn("Myxophage Viscoplastic", spec)
            
            prompt = generator.generate_prompt("Verify myxophage", {"rows": 3, "cols": 3, "timestamps": [0.0]})
            self.assertIn("Test Goal", prompt)
            self.assertIn("Contact Sheet Layout", prompt)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_api_state_and_input(self):
        # Update state
        self.shared_state.update_snapshot({"active_tab": 2, "stamina": 0.5})
        
        # Verify GET /api/state
        url = f"http://127.0.0.1:{self.port}/api/state"
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(data["active_tab"], 2)
            self.assertEqual(data["stamina"], 0.5)

        # Verify POST /api/input
        pygame.event.clear()
        url_input = f"http://127.0.0.1:{self.port}/api/input"
        payload = {
            "event_type": "click",
            "details": {"pos": [400, 300], "button": 1}
        }
        data = json.dumps(payload).encode('utf-8')
        req_post = urllib.request.Request(url_input, data=data, method='POST', headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req_post) as resp:
            self.assertEqual(resp.status, 202)
        
        time.sleep(0.1)
        events = pygame.event.get()
        types = [e.type for e in events]
        self.assertIn(pygame.MOUSEBUTTONDOWN, types)

    def test_remediation_engine_updates_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RemediationEngine(target_dir=tmpdir)
            critique = {
                "accept": False,
                "reject": True,
                "reason": "Tail clipped through floor.",
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
            
            # Verify file was written
            config_file = Path(tmpdir) / "drizzlet_config.json"
            self.assertTrue(config_file.exists())
            with open(config_file, "r") as f:
                data = json.load(f)
            self.assertEqual(data["physics_dt"], 0.008)

if __name__ == '__main__':
    unittest.main()
