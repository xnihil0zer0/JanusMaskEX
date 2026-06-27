# Temporary placeholder for reachability and baseline py_compile checks.
import ast

import re

import math

from typing import List, Dict, Any, Tuple, Optional

def get_leading_whitespace(line: str) -> str:
    match = re.match('^[ \\t]*', line)
    return match.group(0) if match else ''

def detect_indentation(text: str) -> Tuple[str, int]:
    lines = text.splitlines()
    spaces_count = 0
    tabs_count = 0
    indent_sizes = []
    for line in lines:
        if not line.strip():
            continue
        ws = get_leading_whitespace(line)
        if '\t' in ws and ' ' in ws:
            t_c = ws.count('\t')
            s_c = ws.count(' ')
            if t_c >= s_c:
                tabs_count += 1
            else:
                spaces_count += 1
        elif '\t' in ws:
            tabs_count += 1
        elif ' ' in ws:
            spaces_count += 1
            indent_sizes.append(len(ws))
    if tabs_count >= spaces_count and tabs_count > 0:
        return ('\t', 1)
    if not indent_sizes:
        return (' ', 4)
    non_zero = [x for x in indent_sizes if x > 0]
    if not non_zero:
        return (' ', 4)
    gcd = non_zero[0]
    for x in non_zero[1:]:
        gcd = math.gcd(gcd, x)
    if gcd == 1:
        min_val = min(non_zero)
        if min_val in (2, 4, 8):
            return (' ', min_val)
        return (' ', 4)
    return (' ', gcd)

def normalize_patch_indentation(source: str, patch: str) -> str:
    src_char, src_unit = detect_indentation(source)
    patch_char, patch_unit = detect_indentation(patch)
    if src_char == patch_char and src_unit == patch_unit:
        return patch
    lines = patch.splitlines(keepends=True)
    new_lines = []
    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        ws = get_leading_whitespace(line)
        rest = line[len(ws):]
        if patch_char == '\t':
            level = float(len(ws))
        else:
            level = len(ws) / patch_unit
        if src_char == '\t':
            new_ws = '\t' * int(round(level))
        else:
            new_ws = ' ' * int(round(level * src_unit))
        new_lines.append(new_ws + rest)
    return ''.join(new_lines)

def unparse_decorator(d, lines: List[str]) -> str:
    if hasattr(ast, 'unparse'):
        try:
            val = ast.unparse(d).strip()
            if not val.startswith('@'):
                val = '@' + val
            return val
        except Exception:
            pass
    start = d.lineno
    end = getattr(d, 'end_lineno', None)
    if end is None:
        end = start
    decorator_lines = lines[start - 1:end]
    val = ''.join(decorator_lines).strip()
    if not val.startswith('@'):
        val = '@' + val
    return val

def get_line_states(code: str, lines: List[str]) -> List[Dict[str, Any]]:
    n = len(code)
    i = 0
    in_string = None
    paren_level = 0
    in_comment = False
    line_states = []
    line_start_in_string = None
    line_start_paren_level = 0
    while i < n:
        c = code[i]
        if c == '\n':
            line_states.append({'in_string': line_start_in_string, 'paren_level': line_start_paren_level, 'is_clean': line_start_in_string is None and line_start_paren_level == 0})
            line_start_in_string = in_string
            line_start_paren_level = paren_level
            in_comment = False
            i += 1
            continue
        if in_comment:
            i += 1
            continue
        if in_string is None:
            if c == '#':
                in_comment = True
                i += 1
                continue
            elif code[i:i + 3] == '"""':
                in_string = '"""'
                i += 3
                continue
            elif code[i:i + 3] == "'''":
                in_string = "'''"
                i += 3
                continue
            elif c == '"':
                in_string = '"'
                i += 1
                continue
            elif c == "'":
                in_string = "'"
                i += 1
                continue
            elif c in '([{':
                paren_level += 1
            elif c in ')]}':
                paren_level = max(0, paren_level - 1)
            i += 1
        elif in_string == '"""' and code[i:i + 3] == '"""':
            in_string = None
            i += 3
        elif in_string == "'''" and code[i:i + 3] == "'''":
            in_string = None
            i += 3
        elif in_string == '"' and c == '"':
            escaped = False
            k = i - 1
            while k >= 0 and code[k] == '\\':
                escaped = not escaped
                k -= 1
            if not escaped:
                in_string = None
            i += 1
        elif in_string == "'" and c == "'":
            escaped = False
            k = i - 1
            while k >= 0 and code[k] == '\\':
                escaped = not escaped
                k -= 1
            if not escaped:
                in_string = None
            i += 1
        else:
            i += 1
    while len(line_states) < len(lines):
        line_states.append({'in_string': line_start_in_string, 'paren_level': line_start_paren_level, 'is_clean': line_start_in_string is None and line_start_paren_level == 0})
    return line_states

def find_end_line_lexical(lines: List[str], line_states: List[Dict[str, Any]], start_scan_line: int, indent_len: int) -> int:
    end_line = start_scan_line
    for k in range(start_scan_line, len(lines)):
        line = lines[k]
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            if len(get_leading_whitespace(line)) > indent_len:
                end_line = k + 1
            continue
        if not line_states[k]['is_clean']:
            end_line = k + 1
            continue
        if len(get_leading_whitespace(line)) > indent_len:
            end_line = k + 1
            continue
        break
    return end_line

def parse_ast(code: str) -> Optional[List[Dict[str, Any]]]:
    try:
        tree = ast.parse(code)
    except Exception:
        return None
    lines = code.splitlines()
    line_states = get_line_states(code, lines)
    defs = []

    def walk(node, current_path):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = child.name
                path = current_path + [name]
                qualname = '.'.join(path)
                start_line = child.lineno
                if child.decorator_list:
                    start_line = min((d.lineno for d in child.decorator_list))
                end_line = getattr(child, 'end_lineno', start_line)
                if end_line is None:
                    end_line = start_line
                def_line = child.lineno
                indent = get_leading_whitespace(lines[def_line - 1])
                defs.append({'name': name, 'type': 'class' if isinstance(child, ast.ClassDef) else 'function', 'start_line': start_line, 'def_line': def_line, 'end_line': end_line, 'indent': indent, 'qualname': qualname, 'path': path, 'decorators': [unparse_decorator(d, lines) for d in child.decorator_list] if hasattr(child, 'decorator_list') else []})
                walk(child, path)
            else:
                walk(child, current_path)
    walk(tree, [])
    for d in defs:
        d['end_line'] = find_end_line_lexical(lines, line_states, d['end_line'], len(d['indent']))
    return defs

def parse_lexically(code: str) -> List[Dict[str, Any]]:
    lines = code.splitlines()
    line_states = get_line_states(code, lines)
    defs = []
    scope_stack = []
    current_decorators = []
    decorator_start_line = None
    in_multi_line_decorator = False
    for idx, line in enumerate(lines):
        state = line_states[idx]
        stripped = line.strip()
        is_def_line = False
        if stripped.startswith('class ') or stripped.startswith('def ') or stripped.startswith('async def '):
            is_def_line = True
        if is_def_line:
            in_multi_line_decorator = False
        if in_multi_line_decorator:
            current_decorators.append(line)
            if state['paren_level'] == 0:
                in_multi_line_decorator = False
            continue
        if state['is_clean']:
            if not stripped:
                continue
            if stripped.startswith('#'):
                continue
            if stripped.startswith('@'):
                if decorator_start_line is None:
                    decorator_start_line = idx + 1
                current_decorators.append(line)
                next_paren = 0
                if idx + 1 < len(line_states):
                    next_paren = line_states[idx + 1]['paren_level']
                if next_paren > 0:
                    in_multi_line_decorator = True
                continue
            class_match = re.match('^class\\s+([a-zA-Z_][a-zA-Z0-9_]*)', stripped)
            func_match = re.match('^(?:async\\s+)?def\\s+([a-zA-Z_][a-zA-Z0-9_]*)', stripped)
            if class_match or func_match:
                name = class_match.group(1) if class_match else func_match.group(1)
                indent = get_leading_whitespace(line)
                indent_len = len(indent)
                while scope_stack and scope_stack[-1]['indent_len'] >= indent_len:
                    scope_stack.pop()
                qualname = '.'.join([s['name'] for s in scope_stack] + [name])
                scope_stack.append({'name': name, 'indent_len': indent_len})
                start_line = idx + 1
                if decorator_start_line is not None:
                    start_line = decorator_start_line
                defs.append({'name': name, 'type': 'class' if class_match else 'function', 'start_line': start_line, 'def_line': idx + 1, 'indent': indent, 'qualname': qualname, 'path': [s['name'] for s in scope_stack], 'decorators': [d.strip() for d in current_decorators]})
                current_decorators = []
                decorator_start_line = None
            else:
                current_decorators = []
                decorator_start_line = None
                indent_len = len(get_leading_whitespace(line))
                while scope_stack and scope_stack[-1]['indent_len'] >= indent_len:
                    scope_stack.pop()
        else:
            current_decorators = []
            decorator_start_line = None
    for d in defs:
        def_line = d['def_line']
        indent_len = len(d['indent'])
        d['end_line'] = find_end_line_lexical(lines, line_states, def_line, indent_len)
    return defs

def get_definitions(code: str) -> List[Dict[str, Any]]:
    res = parse_ast(code)
    if res is None:
        res = parse_lexically(code)
    return res

def adjust_indentation(lines: List[str], diff_len: int, indent_char: str) -> List[str]:
    adjusted = []
    for line in lines:
        if not line.strip():
            adjusted.append(line)
            continue
        ws = get_leading_whitespace(line)
        rest = line[len(ws):]
        if diff_len > 0:
            new_ws = indent_char * diff_len + ws
            adjusted.append(new_ws + rest)
        elif diff_len < 0:
            to_remove = abs(diff_len)
            new_ws = ws[to_remove:]
            adjusted.append(new_ws + rest)
        else:
            adjusted.append(line)
    return adjusted

def ensure_newline(line: str) -> str:
    if not line.endswith('\n'):
        return line + '\n'
    return line

def find_best_match(p_def: Dict[str, Any], source_defs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    p_path = p_def['path']
    best_match = None
    best_score = (-1, -1000)
    for s_def in source_defs:
        s_path = s_def['path']
        if p_def['type'] != s_def['type']:
            continue
        if len(s_path) >= len(p_path):
            if s_path[-len(p_path):] == p_path:
                score = (len(p_path), -len(s_path))
                if score > best_score:
                    best_score = score
                    best_match = s_def
    return best_match

def is_leaf(d: Dict[str, Any], defs: List[Dict[str, Any]]) -> bool:
    for other in defs:
        if other is d:
            continue
        if len(other['qualname']) > len(d['qualname']) and other['qualname'].startswith(d['qualname'] + '.'):
            return False
    return True

def get_child_indent(parent_indent: str) -> str:
    if '\t' in parent_indent:
        return parent_indent + '\t'
    else:
        return parent_indent + '    '

def has_unmatched_ancestor(p_def: Dict[str, Any], patch_defs: List[Dict[str, Any]], source_defs: List[Dict[str, Any]]) -> bool:
    parts = p_def['path']
    for length in range(1, len(parts)):
        ancestor_path = parts[:length]
        ancestor_p_def = next((d for d in patch_defs if d['path'] == ancestor_path), None)
        if ancestor_p_def:
            match = find_best_match(ancestor_p_def, source_defs)
            if not match:
                return True
    return False

def align_and_deduplicate_patches(source: str, patch: str) -> str:
    if not source.strip():
        return patch
    if not patch.strip():
        return source
    indent_char, _ = detect_indentation(source)
    normalized_patch = normalize_patch_indentation(source, patch)
    source_defs = get_definitions(source)
    all_patch_defs = get_definitions(normalized_patch)
    patch_defs = [d for d in all_patch_defs if not has_unmatched_ancestor(d, all_patch_defs, source_defs)]
    source_lines = source.splitlines(keepends=True)
    normalized_patch_lines = normalized_patch.splitlines(keepends=True)
    edits = []
    matched_patch_defs = set()
    for p_def in patch_defs:
        if is_leaf(p_def, patch_defs):
            s_def = find_best_match(p_def, source_defs)
            if s_def:
                matched_patch_defs.add(p_def['qualname'])
                diff_len = len(s_def['indent']) - len(p_def['indent'])
                lines = normalized_patch_lines[p_def['start_line'] - 1:p_def['end_line']]
                edits.append({'start': s_def['start_line'], 'end': s_def['end_line'], 'lines': adjust_indentation(lines, diff_len, indent_char), 'patch_idx': all_patch_defs.index(p_def)})
    for p_def in patch_defs:
        if not is_leaf(p_def, patch_defs):
            s_def = find_best_match(p_def, source_defs)
            if s_def:
                matched_patch_defs.add(p_def['qualname'])
                diff_len = len(s_def['indent']) - len(p_def['indent'])
                lines = normalized_patch_lines[p_def['start_line'] - 1:p_def['def_line']]
                edits.append({'start': s_def['start_line'], 'end': s_def['def_line'], 'lines': adjust_indentation(lines, diff_len, indent_char), 'patch_idx': all_patch_defs.index(p_def)})
    for p_def in patch_defs:
        if p_def['qualname'] in matched_patch_defs:
            continue
        parts = p_def['path']
        ancestor_s_def = None
        for length in range(len(parts) - 1, 0, -1):
            prefix_path = parts[:length]
            prefix_p_def = next((d for d in all_patch_defs if d['path'] == prefix_path), None)
            if prefix_p_def:
                match = find_best_match(prefix_p_def, source_defs)
                if match:
                    ancestor_s_def = match
                    break
        if ancestor_s_def is not None:
            diff_len = len(get_child_indent(ancestor_s_def['indent'])) - len(p_def['indent'])
            lines = normalized_patch_lines[p_def['start_line'] - 1:p_def['end_line']]
            edits.append({'start': ancestor_s_def['end_line'] + 1, 'end': ancestor_s_def['end_line'], 'lines': adjust_indentation(lines, diff_len, indent_char), 'patch_idx': all_patch_defs.index(p_def)})
        else:
            diff_len = -len(p_def['indent'])
            lines = normalized_patch_lines[p_def['start_line'] - 1:p_def['end_line']]
            edits.append({'start': len(source_lines) + 1, 'end': len(source_lines), 'lines': adjust_indentation(lines, diff_len, indent_char), 'patch_idx': all_patch_defs.index(p_def)})
    covered_patch_lines = set()
    for d in all_patch_defs:
        for idx in range(d['start_line'], d['end_line'] + 1):
            covered_patch_lines.add(idx)
    extra_imports = []
    extra_statements = []
    for idx, line in enumerate(normalized_patch_lines):
        line_num = idx + 1
        if line_num in covered_patch_lines:
            continue
        if not line.strip():
            continue
        if line.strip().startswith('#'):
            extra_statements.append(line)
            continue
        if re.match('^\\s*(?:import\\s+|from\\s+\\S+\\s+import\\s+)', line):
            extra_imports.append(line)
        else:
            extra_statements.append(line)
    if extra_imports:
        edits.append({'start': 1, 'end': 0, 'lines': extra_imports, 'patch_idx': -1})
    if extra_statements:
        edits.append({'start': len(source_lines) + 1, 'end': len(source_lines), 'lines': extra_statements, 'patch_idx': 999999})
    edits.sort(key=lambda e: (e['start'], e['patch_idx']), reverse=True)
    current_lines = list(source_lines)
    for edit in edits:
        start = edit['start']
        end = edit['end']
        new_lines = [ensure_newline(l) for l in edit['lines']]
        if new_lines and start - 2 >= 0 and (start - 2 < len(current_lines)):
            if not current_lines[start - 2].endswith('\n'):
                current_lines[start - 2] = current_lines[start - 2] + '\n'
        current_lines[start - 1:end] = new_lines
    result = ''.join(current_lines)
    if (source.endswith('\n') or patch.endswith('\n')) and (not result.endswith('\n')):
        result += '\n'
    return result
def smooth_boundaries(*args, **kwargs):
    pass
