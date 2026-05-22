import argparse
import errno
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
from typing import Tuple
import yaml

class BriefValidationError(Exception):

    def __init__(self, message: str, missing: List[str]=None, empty: List[str]=None):
        super().__init__(message)
        self.missing = missing if missing is not None else []
        self.empty = empty if empty is not None else []

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

    def to_agent_prompt(self) -> str:
        return f'Title: {self.title}\n\nScope:\n{self.scope}\n\nNon-Goals:\n{self.non_goals}\n\nInputs:\n{self.inputs}\n\nDeliverables:\n{self.deliverables}\n'

class UniqueKeyLoader(yaml.SafeLoader):

    def construct_mapping(self, node, deep=False):
        mapping = set()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError('while constructing a mapping', node.start_mark, f'found duplicate key: {key!r}', key_node.start_mark)
            mapping.add(key)
        return super().construct_mapping(node, deep)
REQUIRED_SECTIONS = {'title', 'scope', 'non_goals', 'inputs', 'deliverables'}

def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """Split optional YAML front matter from the markdown body.

    A document begins with front matter only when its first line is a ``---``
    fence; the matter runs up to the next ``---`` line. The fenced region is
    parsed with ``UniqueKeyLoader`` (rejecting duplicate keys) and returned as a
    mapping alongside the remaining body text. When no opening (or closing)
    fence is present the original text is returned unchanged with an empty
    mapping.
    """
    if not text.startswith('---\n'):
        return ({}, text)
    lines = text.split('\n')
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i] == '---':
            end_idx = i
            break
    if end_idx is None:
        return ({}, text)
    fm_text = '\n'.join(lines[1:end_idx])
    body = '\n'.join(lines[end_idx + 1:])
    try:
        data = yaml.load(fm_text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise BriefValidationError(f'Invalid YAML front matter: {exc}')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BriefValidationError('YAML front matter must be a mapping')
    return (data, body)

def _parse_markdown_sections(text: str) -> dict:
    """Parse a markdown brief into a mapping of required-section key -> content.

    Only level-1 (``#``) headings whose normalized text matches a member of
    ``REQUIRED_SECTIONS`` start a new section. Heading text is normalized by
    stripping, lowercasing, and replacing hyphens/spaces with underscores (so
    ``# Non-Goals`` -> ``non_goals``). Any other line -- including deeper
    headings such as ``## Extra`` -- becomes content of the currently open
    section. Content appearing before the first required heading, or under a
    level-1 heading that is not a required section, is dropped.
    """
    sections: dict = {}
    current = None
    buffer: list = []
    for line in text.splitlines():
        match = re.match('^#\\s+(.+)$', line)
        if match:
            heading = match.group(1).strip().lower().replace('-', '_').replace(' ', '_')
            if heading in REQUIRED_SECTIONS:
                if current is not None:
                    sections[current] = '\n'.join(buffer).strip()
                current = heading
                buffer = []
                continue
        if current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = '\n'.join(buffer).strip()
    return sections

def load_brief(path: Path | str, max_bytes: int=256 * 1024) -> PlanningBrief:
    """Load, validate, and parse a planning brief from disk.

    The file is read as raw bytes; briefs larger than ``max_bytes`` raise
    ``BriefTooLargeError`` and non-UTF-8 content raises ``BriefValidationError``.
    Sections are taken from the parsed markdown body and overlaid with any YAML
    front-matter values for the required keys. Every section in
    ``REQUIRED_SECTIONS`` must be present and non-empty, otherwise a
    ``BriefValidationError`` carrying the ``missing`` and ``empty`` keys is
    raised. On success a frozen ``PlanningBrief`` is returned with the source
    path and a SHA-256 digest of the raw bytes.
    """
    path = Path(path)
    raw_bytes = path.read_bytes()
    actual_bytes = len(raw_bytes)
    if actual_bytes > max_bytes:
        raise BriefTooLargeError(f'Brief exceeds maximum size of {max_bytes} bytes ({actual_bytes} bytes)', actual_bytes=actual_bytes)
    try:
        text = raw_bytes.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise BriefValidationError(f'Brief is not valid UTF-8: {exc}')
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    frontmatter, body = _parse_frontmatter(text)
    sections = _parse_markdown_sections(body)
    for key, value in frontmatter.items():
        if key in REQUIRED_SECTIONS:
            sections[key] = '' if value is None else str(value)
    missing = sorted((key for key in REQUIRED_SECTIONS if key not in sections))
    empty = sorted((key for key in REQUIRED_SECTIONS if key in sections and (not str(sections[key]).strip())))
    if missing or empty:
        raise BriefValidationError(f'Brief is missing or has empty required sections (missing={missing}, empty={empty})', missing=missing, empty=empty)
    return PlanningBrief(title=sections['title'], scope=sections['scope'], non_goals=sections['non_goals'], inputs=sections['inputs'], deliverables=sections['deliverables'], raw_text=text, source_path=str(path), sha256=sha256)
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Load and validate a planning brief')
    parser.add_argument('file', type=Path, help='Path to the brief file')
    args = parser.parse_args()
    try:
        brief = load_brief(args.file)
        print(brief.to_agent_prompt())
        sys.exit(0)
    except BriefValidationError as e:
        print(f'Validation failed: {e}', file=sys.stderr)
        if e.missing:
            print(f'Missing sections: {e.missing}', file=sys.stderr)
        if e.empty:
            print(f'Empty sections: {e.empty}', file=sys.stderr)
        sys.exit(1)
    except BriefTooLargeError as e:
        print(f'File too large: {e.actual_bytes} bytes', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)