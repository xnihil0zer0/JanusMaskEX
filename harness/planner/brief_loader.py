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
        raise NotImplementedError

class BriefTooLargeError(Exception):

    def __init__(self, message: str, actual_bytes: int):
        raise NotImplementedError

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
        raise NotImplementedError

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
    raise NotImplementedError

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