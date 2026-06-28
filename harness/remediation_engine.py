import os
import re
import json
from pathlib import Path
from harness.paths import effective_target_root

class RemediationEngine:
    def __init__(self, target_dir: str = "/mnt/ai-data/Drizzlet"):
        self.target_dir = Path(target_dir).resolve()
        self.config_path = self.target_dir / "drizzlet_config.json"

    def parse_critique_and_apply(self, critique_dict: dict) -> bool:
        """
        Parses the JSON critique object from the vision LLM.
        If reject is True, scans the bugs and reasons for parameters to tweak:
        - "decrease physics_dt" / "physics_dt": decreases physics_dt in Grizzlet config.
        - "increase active ragdoll pd gains" / "pd gains" / "Kp": increases kp_max / kd.
        Returns True if remediation was applied, False otherwise.
        """
        if not critique_dict.get("reject", False):
            return False
            
        reasons_and_suggestions = [critique_dict.get("reason", "")]
        for bug in critique_dict.get("bugs", []):
            reasons_and_suggestions.append(bug.get("description", ""))
            reasons_and_suggestions.append(bug.get("reproduction_suggestion", ""))
            
        combined_text = " ".join(reasons_and_suggestions).lower()
        
        # Load existing config or start with defaults
        config_data = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    config_data = json.load(f)
            except Exception:
                pass
                
        remediated = False
        
        # 1. Decrease physics_dt
        if "decrease physics_dt" in combined_text or "physics_dt" in combined_text or "dt" in combined_text:
            current_dt = config_data.get("physics_dt", 0.016)
            new_dt = max(0.001, current_dt * 0.5)
            match = re.search(r'physics_dt(?:\s+to)?\s+([0-9.]+)', combined_text)
            if match:
                try:
                    val = float(match.group(1))
                    if 0.001 <= val <= 0.1:
                        new_dt = val
                except ValueError:
                    pass
            config_data["physics_dt"] = new_dt
            remediated = True
            
        # 2. Increase active ragdoll PD gains
        if "increase active ragdoll pd gains" in combined_text or "pd gains" in combined_text or "kp" in combined_text or "kd" in combined_text:
            current_kp = config_data.get("kp_max", 150.0)
            current_kd = config_data.get("kd", 2.0)
            config_data["kp_max"] = current_kp * 1.5
            config_data["kd"] = current_kd * 1.2
            remediated = True
            
        if remediated:
            with open(self.config_path, "w") as f:
                json.dump(config_data, f, indent=2)
                
        return remediated
