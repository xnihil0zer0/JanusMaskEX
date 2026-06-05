import argparse
import errno
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import yaml


class BriefValidationError(Exception):
    def __init__(self, message: str, missing: List[str] = None, empty: List[str] = None):
        super().__init__(message)
        self.missing = missing or []
        self.empty = empty or []


class BriefTooLargeError(Exception):
    def __init__(self, message: str, actual_bytes: int):
        super().__init__(message)
        self.actual_bytes = actual_bytes


@dataclass(frozen=True)
class PlanningBrief:
    title: str
    scope: str
    non_goals: str
    inputs: str
    deliverables: str
    raw_text: str
    source_path: str
    sha256: str
    working_dir: str | None = None
    epic: bool = False
    complexity_score: int | None = None
    dependencies: tuple[str, ...] = ()
    interfaces: str | None = None

    def to_agent_prompt(self) -> str:
        return f"""Title: {self.title}
Scope:
{self.scope}

Non-Goals:
{self.non_goals}

Inputs:
{self.inputs}

Deliverables:
{self.deliverables}"""


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key}", key_node.start_mark
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


REQUIRED_SECTIONS = {"title", "scope", "non_goals", "inputs", "deliverables"}


def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    if text.startswith("---\n") or text.startswith("---\r\n"):
        end_idx = text.find("\n---", 3)
        if end_idx != -1:
            fm_text = text[text.find("\n") + 1 : end_idx]
            next_newline = text.find("\n", end_idx + 1)
            if next_newline != -1:
                body_text = text[next_newline + 1 :]
            else:
                body_text = ""
            try:
                fm = yaml.load(fm_text, Loader=UniqueKeyLoader) or {}
                if not isinstance(fm, dict):
                    fm = {}
            except yaml.constructor.ConstructorError as e:
                raise BriefValidationError(f"Duplicate keys in front-matter: {e}")
            except yaml.YAMLError as e:
                raise BriefValidationError(f"Invalid front-matter: {e}")
            return fm, body_text
    return {}, text


def _parse_markdown_sections(text: str) -> dict:
    sections = {}
    current_section = None
    current_content = []

    heading_re = re.compile(r'^#{1,6}\s+(.+)$')

    for line in text.splitlines():
        m = heading_re.match(line)
        is_required_heading = False
        if m:
            raw_title = m.group(1).strip()
            norm_title = raw_title.lower().replace("-", "_").replace(" ", "_")
            if norm_title in REQUIRED_SECTIONS:
                is_required_heading = True
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = norm_title
                current_content = []

        if not is_required_heading:
            if current_section is not None:
                current_content.append(line)

    if current_section:
        sections[current_section] = '\n'.join(current_content).strip()

    return sections


def _coerce_optional_brief_fields(fm: dict) -> dict:
    out: dict = {}
    if not isinstance(fm, dict):
        return out
    normalized: dict = {}
    for k, v in fm.items():
        norm_k = str(k).lower().replace('-', '_').replace(' ', '_')
        normalized[norm_k] = v
    if 'epic' in normalized:
        value = normalized['epic']
        if isinstance(value, bool):
            out['epic'] = value
        elif isinstance(value, str):
            out['epic'] = value.strip().lower() in {'true', '1', 'yes', 'on'}
        else:
            out['epic'] = bool(value)
    if 'complexity_score' in normalized:
        value = normalized['complexity_score']
        try:
            out['complexity_score'] = int(value)
        except (TypeError, ValueError):
            out['complexity_score'] = None
    if 'dependencies' in normalized:
        value = normalized['dependencies']
        if isinstance(value, (list, tuple)):
            out['dependencies'] = tuple((str(item).strip() for item in value if str(item).strip()))
        elif isinstance(value, str):
            out['dependencies'] = tuple((part.strip() for part in value.split(',') if part.strip()))
        else:
            out['dependencies'] = ()
    if 'interfaces' in normalized:
        value = normalized['interfaces']
        out['interfaces'] = None if value is None else str(value)
    return out
def load_brief(path: Path | str, max_bytes: int = 256 * 1024) -> PlanningBrief:
    path = Path(path)

    try:
        resolved_path = path.resolve(strict=True)
    except RuntimeError as e:
        if "loop" in str(e).lower() or "symlink" in str(e).lower():
            raise BriefValidationError(f"Symlink loop detected: {path}")
        raise
    except OSError as e:
        if getattr(e, "errno", None) == errno.ELOOP or "loop" in str(e).lower():
            raise BriefValidationError(f"Symlink loop detected: {path}")
        raise

    stat_size = resolved_path.stat().st_size
    if stat_size > max_bytes:
        raise BriefTooLargeError(f"Brief exceeds {max_bytes} bytes", actual_bytes=stat_size)

    try:
        raw_bytes = resolved_path.read_bytes()
    except OSError as e:
        if getattr(e, "errno", None) == errno.ELOOP or "loop" in str(e).lower():
            raise BriefValidationError(f"Symlink loop detected: {path}")
        raise

    try:
        raw_text = raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        raise BriefValidationError("File is not valid UTF-8")

    normalized_text = raw_text.replace('\r\n', '\n')
    sha256 = hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()

    fm, body_text = _parse_frontmatter(normalized_text)
    md_sections = _parse_markdown_sections(body_text)

    _optional = {"working_dir"}
    fm_normalized = {}
    for k, v in fm.items():
        norm_k = str(k).lower().replace("-", "_").replace(" ", "_")
        if norm_k in REQUIRED_SECTIONS or norm_k in _optional:
            fm_normalized[norm_k] = str(v)

    seen_sections = set(fm_normalized.keys()) | set(md_sections.keys())

    missing = []
    empty = []
    data = {}

    for req in REQUIRED_SECTIONS:
        if req not in seen_sections:
            missing.append(req)
        else:
            val = fm_normalized.get(req)
            if val is None or not str(val).strip():
                val = md_sections.get(req)

            if val is None or not str(val).strip():
                empty.append(req)
            else:
                data[req] = str(val).strip()

    if missing or empty:
        raise BriefValidationError("Validation failed", missing=missing, empty=empty)

    working_dir = fm_normalized.get("working_dir")

    if working_dir:
        from harness.paths import PROJECT_ROOT, _target_is_self
        try:
            _resolved = Path(working_dir).resolve()
            _proot = PROJECT_ROOT.resolve()
            _inside = _resolved == _proot or _proot in _resolved.parents
        except (OSError, ValueError, RuntimeError, Exception):
            _inside = True
        if _inside and not _target_is_self(working_dir):
            raise BriefValidationError(
                f"working_dir {working_dir!r} resolves inside the repo but is not self"
            )

    optional_fields = _coerce_optional_brief_fields(fm)

    return PlanningBrief(
        title=data["title"],
        scope=data["scope"],
        non_goals=data["non_goals"],
        inputs=data["inputs"],
        deliverables=data["deliverables"],
        raw_text=normalized_text,
        source_path=str(path),
        sha256=sha256,
        working_dir=working_dir,
        epic=optional_fields.get("epic", False),
        complexity_score=optional_fields.get("complexity_score", None),
        dependencies=optional_fields.get("dependencies", ()),
        interfaces=optional_fields.get("interfaces", None),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load and validate a planning brief")
    parser.add_argument("file", type=Path, help="Path to the brief file")
    args = parser.parse_args()

    try:
        brief = load_brief(args.file)
        print(brief.to_agent_prompt())
        sys.exit(0)
    except BriefValidationError as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        if e.missing:
            print(f"Missing sections: {e.missing}", file=sys.stderr)
        if e.empty:
            print(f"Empty sections: {e.empty}", file=sys.stderr)
        sys.exit(1)
    except BriefTooLargeError as e:
        print(f"File too large: {e.actual_bytes} bytes", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
