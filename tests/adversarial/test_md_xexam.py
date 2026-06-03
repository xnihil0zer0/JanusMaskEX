"""MD_XEXAM behavioral oracle (REV25 §3 / MD-XEXAM = M-D6 pt2).

prepare_exam_packets must thread the stateful action_sequence /
divergent_step_index into the per-agent failures text, or the cross-examiner
loses the very signal Method D produces.

DEPENDS-ON MD_SERIALIZE_FIELDS: a stateful FuzzFailure cannot even be
constructed until action_sequence/divergent_step_index are real fields, so this
oracle is provable RED-for-the-right-reason only AFTER MD_SERIALIZE_FIELDS
lands. On the field-promoted-but-XEXAM-unwired tree it is RED because the
packet text omits the action sequence; once prepare_exam_packets threads it in,
it is GREEN.
"""
from harness.diff_fuzzer import FuzzFailure
from harness.cross_examiner import prepare_exam_packets


def _stateful_failure():
    return FuzzFailure(
        input_args=[5],
        input_kwargs={},
        result_a=("error", "ValueError('a')"),
        result_b="ok",
        reason="stateful divergence at step 1",
        action_sequence=([5], [("inc", [1]), ("inc", [1])]),
        divergent_step_index=1,
    )


def test_packets_thread_action_sequence_into_text():
    code_a = "class Counter:\n    def inc(self, n):\n        self.v = getattr(self,'v',0)+n\n"
    code_b = "class Counter:\n    def inc(self, n):\n        self.v = getattr(self,'v',0)+2*n\n"
    claude_packet, gemini_packet = prepare_exam_packets(
        code_a, code_b, "Build a Counter", [_stateful_failure()]
    )
    for pkt in (claude_packet, gemini_packet):
        text = pkt.review_prompt
        assert "inc" in text, "action sequence must be threaded into the packet text"
        # the divergent step index must also reach the agent
        assert "stateful divergence at step 1" in text
