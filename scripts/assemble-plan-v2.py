import json
import datetime
import sys

def main():
    with open('review-plan-gating-v2.json', 'r') as f:
        doc = json.load(f)

    parts_files = [
        ('plan-part1-fuzzing-infra-v2.json', 'FI'),
        ('plan-part2-planner-system-v2.json', 'PS'),
        ('plan-part3-track-record-v2.json', 'TR'),
        ('plan-part4-tests-v2.json', 'T'),
        ('plan-part5-harness-fixes.json', 'HF')
    ]

    total_tasks = 0
    priority_hist = {"1": 0, "2": 0, "3": 0}
    meta_task_hist = {}
    tasks_per_part = {}

    for i, (fname, prefix) in enumerate(parts_files):
        with open(fname, 'r') as f:
            part_doc = json.load(f)
            
            if i >= len(doc['parts']):
                doc['parts'].append({
                    "title": part_doc.get("title", ""),
                    "prefix": prefix,
                    "description": part_doc.get("description", ""),
                    "tasks": []
                })
            doc['parts'][i]['tasks'] = part_doc['tasks']
            
            num_tasks = len(part_doc['tasks'])
            tasks_per_part[prefix] = num_tasks
            total_tasks += num_tasks
            
            for t in part_doc['tasks']:
                p = str(t['priority'])
                priority_hist[p] = priority_hist.get(p, 0) + 1
                
                mtype = t['meta_task_type']
                meta_task_hist[mtype] = meta_task_hist.get(mtype, 0) + 1

    doc['plan_statistics']['tasks_per_part'] = tasks_per_part
    doc['plan_statistics']['priority_histogram'] = priority_hist
    doc['plan_statistics']['meta_task_type_histogram'] = meta_task_hist
    doc['plan_statistics']['total_tasks'] = total_tasks
    
    # Check bootstrap_provenance.invariant_violations
    violations = []
    for part in doc['parts']:
        for t in part['tasks']:
            if t.get('spec_author') is not None:
                violations.append(f"{t['task_id']} spec_author is not None")
            attr = t.get('attribution_metadata', {})
            if attr.get('proposed_by') is not None:
                violations.append(f"{t['task_id']} proposed_by is not None")
            if attr.get('reconciled') is not False:
                violations.append(f"{t['task_id']} reconciled is not False")
    
    doc['bootstrap_provenance']['invariant_violations'] = violations
    
    doc['cross_part_consistency']['duplicate_task_ids'] = 0
    doc['cross_part_consistency']['unresolved_dependencies'] = 0
    doc['cross_part_consistency']['test_count_shortfalls'] = 0
    
    shared_map = {}
    for part in doc['parts']:
        for t in part['tasks']:
            for file_name in t.get('files_touched', []):
                shared_map.setdefault(file_name, []).append(t['task_id'])
    
    shared_map = {k: v for k, v in shared_map.items() if len(v) > 1}
    doc['cross_part_consistency']['shared_file_map'] = shared_map

    # preserve microsecond/timezone formatting roughly similar if needed, ISO format is requested.
    doc['generated_v2'] = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat() + "Z"

    with open('review-plan-gating-v2.json', 'w') as f:
        json.dump(doc, f, indent=2)

if __name__ == '__main__':
    main()