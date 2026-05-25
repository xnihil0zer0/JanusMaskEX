# Fixtures Index

## Planning Fixtures

*   `planning/sample_brief.json`: Valid planning brief fixture matching the schema the planner system expects.
*   `planning/draft_claude_v1.json`: Blind draft from Claude.
*   `planning/draft_gemini_v1.json`: Blind draft from Gemini.
*   `planning/draft_divergent_pair.json`: Pair of blind-draft fixtures that agree on 80% of tasks and disagree on the rest.
*   `planning/reconciled_plan.json`: Reconciled plan fixture downstream of the divergent drafts.
*   `planning/plan_with_unknown_taxonomy.json`: Plan with an unknown taxonomy.

## Track Record Fixtures

*   `track_record/empty.json`: Empty track record fixture (zero experience).
*   `track_record/claude_biased.json`: Claude-biased track record fixture.
*   `track_record/gemini_biased.json`: Gemini-biased track record fixture.
*   `track_record/tied.json`: Tied track record fixture.
*   `track_record/event_log_clean.jsonl`: Clean 20-event log.
*   `track_record/event_log_with_reversal.jsonl`: Event log with a known reversed event.

## Taxonomy Fixtures

*   `taxonomies/meta_task_v1.json`: Taxonomy matching preamble v1 tables for meta tasks.
*   `taxonomies/synthesis_target_v1.json`: Taxonomy matching preamble v1 tables for synthesis targets.
*   `taxonomies/meta_task_v1_with_bogus_key.json`: Deliberately-malformed taxonomy with an unknown key used to test rejection paths.

## Other Checked-in Fixtures
*   `mock_agent_scripts/basic_claude.json`: Basic Claude mock.
*   `mock_agent_scripts/basic_gemini.json`: Basic Gemini mock.
*   `mock_agent_scripts/invalid.json`: Intentionally invalid JSON.
*   `plans/sample_plan.json`: Sample plan.
*   `plans/sample_plan_with_gap.json`: Sample plan with gap.

## Autobrief V2 Fixtures
*   `autobrief/claude`: POSIX-shell agent stub for autobrief V2 integration tests. Branches on `TEST_AUTOBRIEF_MODE` to emit timeout / invalid-JSON / valid-shape outputs.
*   `autobrief/gemini`: POSIX-shell agent stub mirroring `autobrief/claude` for the Gemini side of the dual-agent autobrief endpoint.
