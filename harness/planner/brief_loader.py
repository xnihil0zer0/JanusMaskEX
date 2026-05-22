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
                raise yaml.constructor.ConstructorError('while constructing a mapping', node.start_mark, 'found duplicate key %r' % (key,), key_node.start_mark)
            mapping.add(key)
        return super().construct_mapping(node, deep)
REQUIRED_SECTIONS = {'title', 'scope', 'non_goals', 'inputs', 'deliverables'}

def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """Split optional YAML front-matter from the markdown body.

    If ``text`` opens with a ``---`` fence, the YAML between that fence and the
    next ``---`` line is parsed with :class:`UniqueKeyLoader` (which rejects
    duplicate keys) and returned together with the remaining body. Otherwise an
    empty mapping and the original text are returned unchanged. A YAML error
    (e.g. a duplicate key) is surfaced as :class:`BriefValidationError`.
    """
    if not text.startswith('---'):
        return ({}, text)
    match = re.match('^---\\n(.*?)\\n---\\n?(.*)$', text, re.DOTALL)
    if match is None:
        return ({}, text)
    frontmatter_text, body = (match.group(1), match.group(2))
    try:
        data = yaml.load(frontmatter_text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise BriefValidationError(f'Invalid YAML frontmatter: {exc}')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BriefValidationError('Frontmatter must be a YAML mapping')
    return (data, body)

def _parse_markdown_sections(text: str) -> dict:
    """Collect the body of each required ``#`` heading from markdown ``text``.

    Lines are scanned top to bottom. A line that is a markdown heading
    (``#``/``##``/...) whose normalised name is in :data:`REQUIRED_SECTIONS`
    opens a new section; everything until the next such heading becomes that
    section's content. Headings whose name is not required (and any preamble
    before the first required heading) are not section starts -- a non-required
    heading encountered inside an open section is kept verbatim as content,
    while content before the first required heading is dropped. Returns a
    mapping of required section name to its stripped content; sections never
    started are simply absent.
    """
    heading_re = re.compile('^#+\\s+(.+?)\\s*$')
    sections: dict = {}
    current_key = None
    buffer: list = []
    for line in text.split('\n'):
        match = heading_re.match(line)
        key = None
        if match is not None:
            key = match.group(1).strip().lower().replace('-', '_').replace(' ', '_')
        if key is not None and key in REQUIRED_SECTIONS:
            if current_key is not None:
                sections[current_key] = '\n'.join(buffer).strip()
            current_key = key
            buffer = []
        elif current_key is not None:
            buffer.append(line)
    if current_key is not None:
        sections[current_key] = '\n'.join(buffer).strip()
    return sections

def load_brief(path: Path | str, max_bytes: int=256 * 1024) -> PlanningBrief:
    """Load, validate and parse a planning brief from ``path``.

    The file is read as bytes, rejected with :class:`BriefTooLargeError` if it
    exceeds ``max_bytes``, and decoded as UTF-8 (a decode failure becomes a
    :class:`BriefValidationError`). Optional YAML front-matter and the markdown
    ``#`` sections supply the required fields; any required section that is
    absent or empty raises :class:`BriefValidationError` carrying the offending
    names. The returned :class:`PlanningBrief` records the raw text, source path
    and a SHA-256 of the file contents.
    """
    path = Path(path)
    raw_bytes = path.read_bytes()
    actual_bytes = len(raw_bytes)
    if actual_bytes > max_bytes:
        raise BriefTooLargeError(f'Brief is {actual_bytes} bytes, exceeds limit of {max_bytes}', actual_bytes=actual_bytes)
    try:
        text = raw_bytes.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise BriefValidationError(f'Brief is not valid UTF-8: {exc}')
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    frontmatter, body = _parse_frontmatter(text)
    sections = _parse_markdown_sections(body)
    combined: dict = {}
    for key in REQUIRED_SECTIONS:
        if key in frontmatter:
            combined[key] = frontmatter[key]
    combined.update(sections)
    missing: List[str] = []
    empty: List[str] = []
    values: dict = {}
    for key in ('title', 'scope', 'non_goals', 'inputs', 'deliverables'):
        if key not in combined:
            missing.append(key)
            continue
        raw_value = combined[key]
        value = '' if raw_value is None else raw_value if isinstance(raw_value, str) else str(raw_value)
        if not value.strip():
            empty.append(key)
        values[key] = value
    if missing or empty:
        parts = []
        if missing:
            parts.append(f'missing sections: {missing}')
        if empty:
            parts.append(f'empty sections: {empty}')
        raise BriefValidationError('; '.join(parts), missing=missing, empty=empty)
    return PlanningBrief(title=values['title'], scope=values['scope'], non_goals=values['non_goals'], inputs=values['inputs'], deliverables=values['deliverables'], raw_text=text, source_path=str(path), sha256=sha256)
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