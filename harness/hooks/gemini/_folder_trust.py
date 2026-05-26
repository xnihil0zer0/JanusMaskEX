from __future__ import annotations


def _folder_trust_enabled(settings: dict | None) -> bool:
    if not isinstance(settings, dict):
        return False
    
    # Check if folderTrust is specified directly at top-level
    if "folderTrust" in settings:
        ft = settings["folderTrust"]
        if isinstance(ft, bool):
            return ft
        if isinstance(ft, dict):
            return bool(ft.get("enabled"))
            
    # Check if security exists at top-level
    security = settings.get("security")
    if isinstance(security, dict):
        if "folderTrust" in security:
            ft = security["folderTrust"]
            if isinstance(ft, bool):
                return ft
            if isinstance(ft, dict):
                return bool(ft.get("enabled"))
                
    return False
