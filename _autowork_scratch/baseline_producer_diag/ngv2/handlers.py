"""Composition layer wiring the committed ngv2 toolkit into the phase-handler
callables ``ngv2.pipeline.run_pipeline`` consumes.

Pure, stdlib-only, deterministic: every non-deterministic seam (runner,
poc_builder, finders, clock) is injected. The builders assemble the exact
``{'hunt','triage','poc','runner','report','target_spec'}`` dict run_pipeline
drives.
"""
from typing import Callable, Iterable, List, Optional, Sequence
from ngv2.analyzer import analyze
from ngv2.contracts import Finding, PoC
from ngv2.fp_filter import filter_findings
from ngv2.dedup import filter_new
from ngv2.report import build_report

def build_hunt_handler(repo_path: str, *, analyzer_fn: Optional[Callable[..., List[Finding]]]=None, semgrep_finder: Optional[Callable[[str], list]]=None, pattern_finder: Optional[Callable[[str], list]]=None, now_fn: Optional[Callable[[], str]]=None) -> Callable[[], List[Finding]]:
    fn = analyzer_fn or analyze

    def hunt() -> List[Finding]:
        return fn(repo_path, semgrep_finder=semgrep_finder, pattern_finder=pattern_finder, now_fn=now_fn)
    return hunt

def build_triage_handler(*, fp_patterns: Sequence=(), existing_titles: Iterable=()) -> Callable[[List[Finding]], List[Finding]]:

    def triage(findings: List[Finding]) -> List[Finding]:
        dicts = [f.to_dict() for f in findings]
        kept = filter_findings(dicts, fp_patterns)
        rebuilt = [Finding.from_dict(d) for d in kept]
        return filter_new(rebuilt, existing_titles)
    return triage

def build_poc_handler(poc_builder: Callable[[Finding], PoC]) -> Callable[[List[Finding]], List[PoC]]:

    def poc(findings: List[Finding]) -> List[PoC]:
        return [poc_builder(f) for f in findings]
    return poc

def build_report_handler() -> Callable[[object, list], dict]:

    def report(state: object, reports: list) -> dict:
        return build_report(state, reports)
    return report

def build_handlers(repo_path: str, *, runner: Callable, poc_builder: Callable[[Finding], PoC], target_spec: object=None, fp_patterns: Sequence=(), existing_titles: Iterable=(), semgrep_finder: Optional[Callable[[str], list]]=None, pattern_finder: Optional[Callable[[str], list]]=None, now_fn: Optional[Callable[[], str]]=None, analyzer_fn: Optional[Callable[..., List[Finding]]]=None) -> dict:
    return {'hunt': build_hunt_handler(repo_path, analyzer_fn=analyzer_fn, semgrep_finder=semgrep_finder, pattern_finder=pattern_finder, now_fn=now_fn), 'triage': build_triage_handler(fp_patterns=fp_patterns, existing_titles=existing_titles), 'poc': build_poc_handler(poc_builder), 'runner': runner, 'report': build_report_handler(), 'target_spec': target_spec}