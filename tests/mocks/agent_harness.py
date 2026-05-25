import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Union, Any, Tuple
from contextlib import contextmanager

class ScriptExhaustedError(Exception):
    pass

class ScriptedCrashError(Exception):
    def __init__(self, message: str, partial_output: str, offset: int):
        super().__init__(message)
        self.partial_output = partial_output
        self.offset = offset

class TurnOrderError(Exception):
    pass

class TurnMismatchError(Exception):
    pass

class TurnTracker:
    def __init__(self):
        self.expected = "claude"
        self.claude_count = 0
        self.gemini_count = 0
        
    def record_turn(self, name: str):
        if name != self.expected:
            raise TurnOrderError(f"Expected turn {self.expected}, got {name}")
        if name == "claude":
            self.claude_count += 1
            self.expected = "gemini"
        else:
            self.gemini_count += 1
            self.expected = "claude"
            
    def verify(self):
        if self.claude_count != self.gemini_count:
            raise TurnMismatchError(f"Turn mismatch: claude={self.claude_count} vs gemini={self.gemini_count}")

class MockAgent:
    def __init__(self, 
                 scripted_responses: Optional[List[Dict]] = None, 
                 fixture_path: Optional[Union[str, Path]] = None,
                 crash_after_n_chars: Optional[int] = None,
                 return_invalid_json: bool = False,
                 hang_for_seconds: Optional[float] = None,
                 _shared_tracker: Optional[TurnTracker] = None,
                 _agent_name: Optional[str] = None):
        if fixture_path is not None:
            path = Path(fixture_path)
            with open(path, "r", encoding="utf-8") as f:
                self.scripted_responses = json.load(f)
        elif scripted_responses is not None:
            self.scripted_responses = scripted_responses
        else:
            self.scripted_responses = []
            
        self.crash_after_n_chars = crash_after_n_chars
        self.return_invalid_json = return_invalid_json
        self.hang_for_seconds = hang_for_seconds
        
        self.received_prompts: List[str] = []
        self._cursor = 0
        self._shared_tracker = _shared_tracker
        self._agent_name = _agent_name

    def next_response(self, prompt: str) -> Union[Dict, str]:
        if self._shared_tracker and self._agent_name:
            self._shared_tracker.record_turn(self._agent_name)
            
        self.received_prompts.append(prompt)
        
        if self.hang_for_seconds is not None:
            time.sleep(self.hang_for_seconds)
            
        if self._cursor >= len(self.scripted_responses):
            raise ScriptExhaustedError("Script exhausted")
            
        response_obj = self.scripted_responses[self._cursor]
        self._cursor += 1
        
        if self.return_invalid_json:
            return '{"this_is_invalid_json": ' + json.dumps(response_obj)
            
        if self.crash_after_n_chars is not None:
            # Try to get string representation of response to simulate partial output
            if isinstance(response_obj, dict) and 'response' in response_obj:
                full_text = response_obj['response']
            else:
                full_text = json.dumps(response_obj)
                
            if len(full_text) > self.crash_after_n_chars:
                partial = full_text[:self.crash_after_n_chars]
                raise ScriptedCrashError(
                    f"Simulated crash after {self.crash_after_n_chars} chars", 
                    partial_output=partial,
                    offset=self.crash_after_n_chars
                )
            else:
                raise ScriptedCrashError(
                    "Simulated crash after full emission", 
                    partial_output=full_text,
                    offset=len(full_text)
                )
                
        return response_obj
        
    def reset(self):
        self.received_prompts.clear()
        self._cursor = 0

@contextmanager
def paired_mocks(claude_fixture_path: Union[str, Path], gemini_fixture_path: Union[str, Path]):
    tracker = TurnTracker()
    claude = MockAgent(fixture_path=claude_fixture_path, _shared_tracker=tracker, _agent_name="claude")
    gemini = MockAgent(fixture_path=gemini_fixture_path, _shared_tracker=tracker, _agent_name="gemini")
    
    yield claude, gemini
    
    tracker.verify()
