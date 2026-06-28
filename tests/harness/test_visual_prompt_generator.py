import unittest
import os
import tempfile
from harness.visual_prompt_generator import OptimizedVisualPromptGenerator, parse_json_response

class TestVisualPromptGenerator(unittest.TestCase):
    def test_parse_markdown_doc_and_relevancy(self):
        doc_content = """# Section 1: Myxophage rolling
The Myxophage viscoplastic rolling is simulated using non-Newtonian dynamics.
It must roll on contact surfaces and handle deformation stress.

# Section 2: Combat & perm HUD
The dielectric CORONA spark HUD elements indicate relative permittivity of wetness.
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(doc_content)
            temp_path = f.name
            
        try:
            generator = OptimizedVisualPromptGenerator(temp_path)
            # Relevancy check for myxophage
            spec = generator.extract_relevant_spec("Verify myxophage viscoplastic rolling stability")
            self.assertIn("Myxophage rolling", spec)
            self.assertIn("viscoplastic", spec)
            
            # Relevancy check for hud
            spec_hud = generator.extract_relevant_spec("Check dielectric permittivity HUD sparks")
            self.assertIn("Combat & perm HUD", spec_hud)
            self.assertIn("relative permittivity", spec_hud)
            
            # No match
            spec_none = generator.extract_relevant_spec("Some random thing")
            self.assertIn("Standard rendering", spec_none)
            
            # Generate prompt
            prompt = generator.generate_prompt("Verify myxophage rolling", {"rows": 3, "cols": 3, "timestamps": [0.0, 0.5, 1.0]})
            self.assertIn("Verify myxophage rolling", prompt)
            self.assertIn("Contact sheet grid", prompt)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_parse_json_response_fences(self):
        raw_res = """```json
{
  "accept": false,
  "reject": true,
  "reason": "clipless",
  "bugs": []
}
```"""
        parsed = parse_json_response(raw_res)
        self.assertFalse(parsed["accept"])
        self.assertTrue(parsed["reject"])
        self.assertEqual(parsed["reason"], "clipless")

if __name__ == '__main__':
    unittest.main()
