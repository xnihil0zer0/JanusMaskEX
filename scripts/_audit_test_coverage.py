import argparse
import ast
import json
import os
import sys
from pathlib import Path
import glob

def get_tests_from_ast(tests_dir):
    tests = set()
    for root, _, files in os.walk(tests_dir):
        # Exclude tests/fixtures/ completely to avoid counting fixture tests
        if 'fixtures' in Path(root).parts:
            continue
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    node = ast.parse(file.read(), filename=path)
                for item in ast.walk(node):
                    if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'):
                        tests.add(item.name)
            except Exception as e:
                print(f"Warning: Could not parse {path}: {e}", file=sys.stderr)
    return tests

def extract_json_from_md(content):
    if '```json' in content:
        try:
            return content.split('```json')[1].split('```')[0].strip()
        except IndexError:
            pass
    return content # fallback

def parse_plan_files(files):
    tasks = []
    for f in files:
        p = Path(f)
        if not p.exists():
            print(f"Warning: Plan file missing: {f}", file=sys.stderr)
            continue
        try:
            content = p.read_text(encoding='utf-8')
            if p.suffix == '.md':
                content = extract_json_from_md(content)
            data = json.loads(content)
            if 'tasks' in data:
                tasks.extend(data['tasks'])
        except Exception as e:
            print(f"Warning: Could not parse json from {f}: {e}", file=sys.stderr)
    return tasks

def audit_coverage(plan_files, tests_dir="tests"):
    found_tests = get_tests_from_ast(tests_dir)
    tasks = parse_plan_files(plan_files)
    
    report = {
        "tasks": {},
        "totals": {
            "found": 0,
            "required": 0
        }
    }
    
    all_ok = True
    
    for task in tasks:
        task_id = task.get("task_id", "UNKNOWN")
        meta_type = task.get("meta_task_type", "")
        test_spec = task.get("test_spec")
        
        is_meta_test = meta_type.startswith("test_")
        
        if not test_spec:
            status = "MISSING"
            gap = 0
            listed_tests = []
            min_count = 0
            found_count = 0
            typo_suspected = []
        else:
            min_count = test_spec.get("minimum_test_count", 0)
            
            listed_tests = []
            for category in ["unit_tests", "integration_tests", "property_tests", "regression_tests"]:
                for t in test_spec.get(category, []):
                    name = t.get("name")
                    if name:
                        listed_tests.append(name)
                    
            typo_suspected = []
            actual_found_tests = []
            
            for t in listed_tests:
                if t in found_tests:
                    actual_found_tests.append(t)
                else:
                    typo_suspected.append(t)
                    
            found_count = len(actual_found_tests)
            gap = min_count - found_count if found_count < min_count else 0
            
            if is_meta_test:
                status = "EXEMPT_RATIO"
            elif found_count >= min_count and len(listed_tests) > 0:
                status = "OK"
            elif found_count > 0:
                status = "UNDER"
            else:
                status = "MISSING"
                
        if status in ("UNDER", "MISSING") and not is_meta_test:
            all_ok = False
            
        task_report = {
            "listed_count": len(listed_tests),
            "found_count": found_count,
            "gap": gap,
            "status": status,
            "minimum_test_count": min_count
        }
        
        if typo_suspected:
            task_report["typo_suspected"] = typo_suspected
            print(f"Warning: Task {task_id} lists tests not found in suite: {typo_suspected}", file=sys.stderr)
            
        report["tasks"][task_id] = task_report
        
        if not is_meta_test:
            report["totals"]["found"] += found_count
            report["totals"]["required"] += min_count
            
    return report, all_ok

def main():
    parser = argparse.ArgumentParser(description="Audit test coverage against plan tasks.")
    parser.add_argument("plan_files", nargs="*", help="Plan files to parse (.json or .md)")
    parser.add_argument("--tests-dir", default="tests", help="Directory containing tests")
    parser.add_argument("--log-file", default="logs/test_coverage_audit.json", help="Output JSON log file")
    
    args = parser.parse_args()
    
    if not args.plan_files:
        files = glob.glob("plan-part*.json") + glob.glob("plan-gating-design-document.md") + glob.glob("plan-gating-design-document*.json")
        args.plan_files = sorted(list(set(files)))
        
    report, all_ok = audit_coverage(args.plan_files, args.tests_dir)
    
    os.makedirs(os.path.dirname(args.log_file), exist_ok=True)
    with open(args.log_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        
    print(f"Coverage audit complete. Detailed log written to {args.log_file}")
    
    for task_id, task_data in report["tasks"].items():
        print(f"Task {task_id}: {task_data['status']} (Found: {task_data['found_count']}, Required: {task_data['minimum_test_count']}, Gap: {task_data['gap']})")
        
    print(f"\nTotals (excluding test_* meta types):")
    print(f"Found: {report['totals']['found']}")
    print(f"Required: {report['totals']['required']}")
    
    if not all_ok:
        print("\nAudit failed: Some non-exempt tasks are missing required tests.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAudit passed.")
        sys.exit(0)

if __name__ == "__main__":
    main()
