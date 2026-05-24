import pytest
from harness.hooks.gemini._folder_trust import _folder_trust_enabled

def test_folder_trust_enabled_basic():
    assert _folder_trust_enabled({"folderTrust": True}) is True
    assert _folder_trust_enabled({"folderTrust": False}) is False
    assert _folder_trust_enabled({}) is False
    assert _folder_trust_enabled(None) is False
