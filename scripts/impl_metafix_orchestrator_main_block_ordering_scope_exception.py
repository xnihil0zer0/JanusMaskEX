"""Scope exception for META-FIX-ORCHESTRATOR-MAIN-BLOCK-ORDERING.

G3a (commit b8ee8a5) appended ``_vcmd_scrubbed_env`` to harness/orchestrator.py
via ``_ast_merge``'s append-on-unmatched branch. ``_ast_merge`` places
appended nodes at the literal END of tree.body — AFTER the existing
``if __name__ == '__main__':`` block (which is also a top-level node in
``tree.body`` and at module-level by line number 1279, but NOT actually at the
end of file before G3a). When the orchestrator runs as a daemon
(``python -u harness/orchestrator.py``), Python executes top-to-bottom:
the ``if __name__`` block fires at line 1279 BEFORE the post-block defs
(``apply``, ``files_touched``, ``_vcmd_scrubbed_env``) are registered in
module globals. ``main()`` runs ``run_pipeline`` runs ``_auto_commit_accepted``
which references ``_vcmd_scrubbed_env()`` and gets ``NameError``.

Empirical: G8 and G10 both committed (commits 6f52adc + 2a82a26 visible in
``git log``) but the verification step never ran — ``NameError`` raised
after the git commit but before ``subprocess.run`` was reached. The
``Fatal error in pipeline`` row in ``logs/harness.log`` for both dispatches
captures the traceback.

G10 then compounded the problem: it added four MORE post-block defs
(``_rewrite_import_calls``, ``_matches_import_call_rule``, ``_FIX_CLASSES``,
``_try_auto_repair``) plus pipeline calls to ``_try_auto_repair`` from within
``run_pipeline``. So today every dispatch path through ``run_pipeline`` is
broken — the AST-validation failure branch references ``_try_auto_repair``
which is also post-``if __name__`` and therefore undefined at daemon-run time.

This META direct-impl moves the ``if __name__ == '__main__':`` block to the
actual end of file so all currently-post-block defs land BEFORE the entry
point and become reachable when run as ``__main__``. One-shot reorder; no
behaviour change beyond restoring the original intent of G3a / G10.

Long-term fix (separate brief — to be filed as G11 if dispatched): extend
``harness/git_integration.py:_ast_merge`` to detect a top-level
``if __name__ == '__main__':`` node and insert appended-on-unmatched nodes
BEFORE that node rather than at the end of ``tree.body``. That way future
self-fix dispatches don't reintroduce this class.
"""


def is_in_scope(path: str) -> bool:
    return path == "harness/orchestrator.py"
