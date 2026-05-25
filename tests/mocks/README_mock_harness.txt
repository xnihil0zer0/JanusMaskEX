# Mock Agent Harness

This module provides a reusable library for standing up mock Claude and mock Gemini agents that respond with scripted JSON.

Every downstream planning/integration/e2e test that needs an agent imports from here instead of re-implementing mocking. Also supports deliberately-broken scenarios (crash mid-draft, invalid JSON, timeout, partial output) so failure-path tests share one surface.
