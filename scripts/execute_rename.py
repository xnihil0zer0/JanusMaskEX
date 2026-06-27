import os

repo_root = "/home/xnihil0zer0/AI-Data/JanusMaskEX"

files_to_modify = [
    ".gitignore",
    "DESIGN_self_healing_remediation_agent.md",
    "Makefile",
    "PLAN_autonomous_resume.md",
    "README.md",
    "docs/ARCHITECTURE_CONTRACTS.md",
    "harness/rebuild/__init__.py",
    "harness/state_reconciler.py",
    "scripts/_ngv2_detonation_retry.sh",
    "scripts/_phase2_run_child.sh",
    "scripts/cleanup_stale_artifacts.py",
    "tests/adversarial/test_agent_isolation.py",
    "tests/adversarial/test_daemon_control_isolation_hooks.py",
    "tests/adversarial/test_flag2_orch.py",
    "tests/adversarial/test_h2a_jail_verify.py",
    "tests/adversarial/test_sec1c_orchacc_proxy_wrap.py",
    "tests/adversarial/test_sec2_jail_extra_ro_prefix.py",
    "tests/adversarial/test_sec5_verify_extra_binds.py",
    "tests/drive_backup/test_archiver.py",
    "tests/drive_backup/test_drive_backup_local_retention_one.py",
    "tests/drive_backup/test_drive_backup_repo_resolution.py",
    "tests/drive_backup/test_install_hooks.py",
    "tests/drive_backup/test_ledger.py",
    "tests/drive_backup/test_ledger_repo_scoped.py",
    "tests/drive_backup/test_uploader.py",
    "tests/harness/test_brief_loader_required_child_slugs.py",
    "tests/harness/test_decomposer_propagate_files_touched.py",
    "tests/harness/test_stale_e2e_capstone.py",
    "tests/harness/test_wireup_contract_briefloader.py",
    "tests/harness/test_wireup_contract_cli_thread.py",
    "tests/overseer/test_tmux_seams.py",
    "tests/planner/test_keep_required_oracle_normalize.py",
    "tests/security/test_sec1_failclosed_verify_orchacc.py",
    "tests/test_autowork_parallelism.py",
    "tests/test_rebuild_task_shell_quote_wired.py",
    "tests/test_rebuild_task_testcmd_quote_wired.py",
    "tools/webui_static/app.js",
    "config/drive_backup_modules.yaml",
]

# Walk .agents/agy-pool to include seeded config files and wrappers
for root, dirs, files in os.walk(os.path.join(repo_root, ".agents/agy-pool")):
    for file in files:
        file_path = os.path.join(root, file)
        if os.path.islink(file_path):
            continue
        # Check standard config formats or agent wrappers
        if file.endswith((".json", ".txt", ".sh", ".log", "agentapi", "settings.json", "projects.json")):
            files_to_modify.append(os.path.relpath(file_path, repo_root))

# Remove duplicates & sort
files_to_modify = sorted(list(set(files_to_modify)))

print(f"Starting migration scan on {len(files_to_modify)} files...")

updated_count = 0
for rel_path in files_to_modify:
    abs_path = os.path.join(repo_root, rel_path)
    if not os.path.exists(abs_path):
        continue
    
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        new_content = content.replace("/home/xnihil0zer0/JanusMaskJR", "/home/xnihil0zer0/AI-Data/JanusMaskEX")
        new_content = new_content.replace("/home/xnihil0zer0/JanusMask", "/home/xnihil0zer0/AI-Data/JanusMaskEX")
        new_content = new_content.replace("JanusMaskJR_agentwork", "JanusMaskEX_agentwork")
        new_content = new_content.replace("JanusMaskJR", "JanusMaskEX")
        new_content = new_content.replace("janusmaskjr", "janusmaskex")
        
        if new_content != content:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Updated: {rel_path}")
            updated_count += 1
    except Exception as e:
        print(f"Error updating {rel_path}: {e}")

print(f"Migration completed! Updated {updated_count} files.")
