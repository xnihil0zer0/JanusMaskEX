"""Child-brief markdown serializer for the hierarchical (epic) planner.

Turns a reconciled child-brief dict (slug/title/scope/non_goals/inputs/
deliverables + optional dependencies/interfaces) into markdown that
``harness.planner.brief_loader.load_brief`` accepts, so the epic decomposition
pipeline can emit re-plannable ``brief_hooks_<slug>.md`` files.
"""

def serialize_child_brief_to_markdown(brief_data: dict) -> str:
    """Serialize a reconciled child-brief dict into ``load_brief``-compatible markdown.

    The output always contains the five required section headings
    (``# Title``, ``# Scope``, ``# Non-Goals``, ``# Inputs``,
    ``# Deliverables``) followed by a blank line and the corresponding value
    from ``brief_data`` (missing keys render as an empty string).

    When ``brief_data`` carries a non-empty ``working_dir`` string, a non-empty
    ``dependencies`` list and/or a non-empty ``interfaces`` string, a leading
    YAML frontmatter block (delimited by ``---`` lines) is emitted carrying
    those optional keys. When none of the optionals is present the frontmatter
    block is omitted entirely so the brief still loads cleanly.
    """

    def _double_quote(text) -> str:
        s = str(text)
        s = s.replace('\\', '\\\\')
        s = s.replace('"', '\\"')
        s = s.replace('\n', '\\n')
        s = s.replace('\r', '\\r')
        s = s.replace('\t', '\\t')
        return '"' + s + '"'

    def _render_content(value) -> str:
        if value is None:
            return ''
        if isinstance(value, (list, tuple)):
            return '\n'.join((str(item) for item in value))
        return str(value)
    sections = [('# Title', 'title'), ('# Scope', 'scope'), ('# Non-Goals', 'non_goals'), ('# Inputs', 'inputs'), ('# Deliverables', 'deliverables')]
    dependencies = brief_data.get('dependencies')
    interfaces = brief_data.get('interfaces')
    frontmatter_lines: list = []
    if isinstance(dependencies, (list, tuple)) and len(dependencies) > 0:
        frontmatter_lines.append('dependencies:')
        for dep in dependencies:
            frontmatter_lines.append('  - ' + _double_quote(dep))
    if isinstance(interfaces, str) and interfaces.strip():
        frontmatter_lines.append('interfaces: ' + _double_quote(interfaces))
    working_dir = brief_data.get('working_dir')
    if isinstance(working_dir, str) and working_dir.strip():
        frontmatter_lines.append('working_dir: ' + _double_quote(working_dir))
    lines: list = []
    if frontmatter_lines:
        lines.append('---')
        lines.extend(frontmatter_lines)
        lines.append('---')
        lines.append('')
    for index, (heading, key) in enumerate(sections):
        lines.append(heading)
        lines.append('')
        lines.append(_render_content(brief_data.get(key, '')))
        if index != len(sections) - 1:
            lines.append('')
    return '\n'.join(lines) + '\n'