"""Regression-lock EG1/EG2: gen_testless authoring is gated + reuse-safe.

EG1 -- ``ensure_testless_oracles`` was NOT gated by ``--only``: a single-unit
keystone re-authored oracles for the WHOLE descriptor (~6 min/unit wasted).
EG2 -- ``--resume`` re-authored oracles that already exist on disk, and the
author EMPTIES the file before writing, so a failed re-author DESTROYS a
previously-good oracle. The fix gates authoring to the ``only`` unit's module and
reuses a non-empty on-disk generated oracle instead of re-authoring it.
"""
from __future__ import annotations

import harness.rebuild.loop as loop
from harness.rebuild import discover

MOD = (
    "import re\n\n\n"
    "def alpha(x: int) -> int:\n    return x + 1\n\n\n"
    "def beta(s: str) -> str:\n    return re.sub(r'[a-z]', '*', s)\n"
)


def _gen_for(prompt):
    if "def alpha" in prompt:
        return ("from mathmod import alpha\n\n\n"
                "def test_alpha_increments():\n    assert alpha(1) == 2\n",
                "python -m pytest -q")
    return ("from mathmod import beta\n\n\n"
            "def test_beta_stars_lowercase():\n    assert beta('aB') == '*B'\n",
            "python -m pytest -q")


def _desc(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mathmod.py").write_text(MOD, encoding="utf-8")
    return discover.build_descriptor(
        src, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        modules=["mathmod.py"], test_files=[], dependencies=[], requirements_files=[],
    )


def test_eg1_only_gates_authoring_to_one_unit(tmp_path):
    desc = _desc(tmp_path)
    calls = []

    def counting_gen(prompt, *, session_dir, attempt):
        calls.append(prompt)
        return _gen_for(prompt)

    loop.ensure_testless_oracles(desc, gen_fn=counting_gen, only="alpha")

    # Only the ``alpha`` unit's oracle was authored -- NOT the whole module.
    assert len(calls) == 1
    assert "def alpha" in calls[0] and "def beta" not in calls[0]
    out_test = (tmp_path / "out" / "test_mathmod_generated.py").read_text(encoding="utf-8")
    assert "test_alpha" in out_test
    assert "test_beta" not in out_test


def test_eg1_only_skips_modules_not_containing_the_unit(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mathmod.py").write_text(MOD, encoding="utf-8")
    (src / "other.py").write_text("def gamma(x: int) -> int:\n    return x * 2\n", encoding="utf-8")
    desc = discover.build_descriptor(
        src, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        modules=["mathmod.py", "other.py"], test_files=[], dependencies=[], requirements_files=[],
    )
    calls = []

    def counting_gen(prompt, *, session_dir, attempt):
        calls.append(prompt)
        return _gen_for(prompt)

    loop.ensure_testless_oracles(desc, gen_fn=counting_gen, only="alpha")

    # ``other.py`` (no ``alpha``) is not authored at all.
    assert len(calls) == 1
    assert not (tmp_path / "out" / "test_other_generated.py").exists()


def test_eg2_resume_reuses_existing_on_disk_oracle(tmp_path):
    desc = _desc(tmp_path)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    # A previously-authored, non-empty oracle already on disk.
    prior = "from mathmod import alpha\n\n\ndef test_alpha_increments():\n    assert alpha(1) == 2\n"
    (out / "test_mathmod_generated.py").write_text(prior, encoding="utf-8")

    calls = []

    def counting_gen(prompt, *, session_dir, attempt):
        calls.append(prompt)
        return _gen_for(prompt)

    gen = loop.ensure_testless_oracles(desc, gen_fn=counting_gen, reuse_existing=True)

    # No re-author call -- the good on-disk oracle is preserved and registered.
    assert calls == []
    assert (out / "test_mathmod_generated.py").read_text(encoding="utf-8") == prior
    assert "test_mathmod_generated.py" in desc.test_files
    assert "{unit}" in desc.unit_test_selector
    assert gen["mathmod.py"].attempts == 0


def test_eg2_fresh_run_still_authors(tmp_path):
    # Without reuse_existing (a fresh, non-resume run) a present-but-stale file is
    # NOT trusted -- authoring proceeds normally.
    desc = _desc(tmp_path)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "test_mathmod_generated.py").write_text("# stale\n", encoding="utf-8")

    calls = []

    def counting_gen(prompt, *, session_dir, attempt):
        calls.append(prompt)
        return _gen_for(prompt)

    loop.ensure_testless_oracles(desc, gen_fn=counting_gen, reuse_existing=False)
    assert len(calls) == 2  # both units authored fresh
