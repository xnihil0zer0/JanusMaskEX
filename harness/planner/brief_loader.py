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
    raise NotImplementedError

def load_brief(path: Path | str, max_bytes: int=256 * 1024) -> PlanningBrief:
    raise NotImplementedError
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