import os
import re
import json
from typing import Dict, Any, Tuple, List

class OptimizedVisualPromptGenerator:
    def __init__(self, design_doc_path: str):
        self.design_doc_path = design_doc_path
        self.sections: List[Tuple[str, str]] = []
        self._load_and_parse_doc()

    def _load_and_parse_doc(self):
        if not os.path.exists(self.design_doc_path):
            return
        with open(self.design_doc_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        pattern = re.compile(r'^(#+ [^\n]+)', re.MULTILINE)
        parts = pattern.split(content)
        
        if parts[0].strip():
            self.sections.append(("", parts[0].strip()))
            
        for i in range(1, len(parts), 2):
            heading = parts[i]
            body = parts[i+1] if i+1 < len(parts) else ""
            self.sections.append((heading, body.strip()))

    def extract_relevant_spec(self, goal: str) -> str:
        keywords = {
            "myxophage": ["myxophage", "viscoplastic", "rolling", "cahn-hilliard"],
            "scolopendrid": ["scolopendrid", "metachronal", "gait", "ik"],
            "pterovelum": ["pterovelum", "lift", "aerodynamic", "stall", "glider"],
            "adhesipod": ["adhesipod", "wall-grip", "adhesion", "jkr", "peeling"],
            "saltator": ["saltator", "spring-leg", "muscle", "damping"],
            "bathynaut": ["bathynaut", "cephalojet", "propulsion", "cavitation"],
            "geo-borer": ["geo-borer", "boring", "peristaltic"],
            "glossa-raptor": ["glossa-raptor", "viscoelastic", "swing", "cable"],
            "wfc": ["wfc", "wave function collapse", "buckling", "column"],
            "biome": ["canopy", "shallows", "bioluminescent", "spireland", "chasm"],
            "ecosystem": ["ecosystem", "flocking", "acoustic", "sound"],
            "combat": ["diegetic", "permittivity", "hud", "bleeding"]
        }
        lowered_goal = goal.lower()
        matched_categories = [cat for cat, terms in keywords.items() if any(term in lowered_goal for term in terms)]
        
        if not matched_categories:
            return "Standard rendering: deep slate colors, Outfit font, 60fps refresh."
            
        best_section = None
        best_score = -1
        
        for heading, body in self.sections:
            heading_lower, body_lower = heading.lower(), body.lower()
            heading_matches = sum(1 for cat in matched_categories for term in keywords[cat] if term in lowered_goal and term in heading_lower)
            body_matches = sum(1 for cat in matched_categories for term in keywords[cat] if term in lowered_goal and term in body_lower)
            
            if heading_matches > 0 or body_matches > 0:
                match = re.match(r'^(#+)', heading)
                heading_level = len(match.group(1)) if match else 0
                score = (heading_matches * 100) + (body_matches * 10) + heading_level
                if score > best_score:
                    best_score = score
                    best_section = f"{heading}\n{body}"
                    
        return best_section if best_section else "Standard rendering: deep slate colors, Outfit font, 60fps refresh."

    def generate_prompt(self, goal: str, grid_meta: Dict[str, Any]) -> str:
        spec = self.extract_relevant_spec(goal)
        layout = f"Contact sheet grid: {grid_meta.get('rows', 3)}x{grid_meta.get('cols', 3)}.\n"
        for i, ts in enumerate(grid_meta.get("timestamps", [])):
            layout += f"- Frame {i}: Time {ts:.2f}s.\n"

        return f"""You are the visual verification oracle for Drizzlet.
Analyze the attached visual contact sheet representing a simulation test run.
A red outline and numbering (0-8) have been added to the corners of each frame in the contact sheet.

### 1. Test Goal
{goal}

### 2. Physical/Rendering Specs
{spec}

### 3. Contact Sheet Layout
{layout}

### 4. Output Requirement
Return a JSON object containing:
- "accept" (bool): true if visual rendering matches all specs and has no bugs.
- "reject" (bool): true if there are layout bugs, overflows, clipping, or incorrect physical transitions.
- "reason" (str): summary of verdict.
- "bugs" (array of objects): each with "id", "component", "severity" (critical/major/minor), "description", "bounding_box" [ymin, xmin, ymax, xmax] normalized 0-1000, "spec_violation", and "reproduction_suggestion".
"""

def parse_json_response(raw_response: str) -> dict:
    """Robust parser that strips markdown code fences before parsing JSON."""
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        match = re.search(r'^```(?:json)?\s*(.*?)\s*```$', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        sub_match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
        if sub_match:
            return json.loads(sub_match.group(1))
        raise
