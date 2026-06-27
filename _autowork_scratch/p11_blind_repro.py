import logging, sys, json
logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format='%(levelname)s %(name)s: %(message)s')
from pathlib import Path
from harness.planner.brief_loader import load_brief
from harness.orchestrator import load_config
from harness.planner import blind_draft as bd

brief = load_brief(Path('brief_hooks_p11_build_evidence_perphase.md'))
config = load_config(Path('harness/config.yaml'))
state_dir = Path('state')
print('brief.working_dir =', getattr(brief,'working_dir',None), file=sys.stderr)
res = bd.run_blind_drafts(brief, config, state_dir)
print('=== RESULT ===')
print('claude_status =', res.claude_status, ' claude_draft is None:', res.claude_draft is None)
print('gemini_status =', res.gemini_status, ' gemini_draft is None:', res.gemini_draft is None)
