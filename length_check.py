from harness.hooks.console import ConsoleStreamer, _stream
import json

lines = []
import harness.hooks.console as console
console._stream = lambda msg: lines.append(msg)
console._agent_label = lambda aid: f"LBL<{aid}>"
console._divider = lambda aid, char="─", width=60: f"DIV<{char}>"
console._code_preview = lambda code, max_lines=12: f"PREVIEW<n={max_lines},len={len(code)}>"

cs = ConsoleStreamer("claude", "S")

lines.clear()
cs.on_submit_accepted("print(1)", submission_num=2, max_subs=5, round_number=1, warnings=[])
print("on_submit_accepted:")
for i, l in enumerate(lines): print(f"{i}: {l}")

lines.clear()
cs.on_submit_rejected("srccode", [{"line": 1, "rule": "no-import", "message": "bad import"}, {"line": 4, "rule": "no-eval", "message": "eval used"}])
print("on_submit_rejected:")
for i, l in enumerate(lines): print(f"{i}: {l}")
