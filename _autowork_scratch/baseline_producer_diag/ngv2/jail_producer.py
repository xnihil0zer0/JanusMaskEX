"""ngv2/jail_producer.py -- implementation of produce_jail_input."""
from __future__ import annotations
import shutil
from typing import Callable, Any
from ngv2.poc_runner_live import build_detonation_jail_argv, LiveRunnerError

def produce_jail_input(provision_artifact: Any, repo_root: str | None, work_dir: str, which_fn: Callable[[str], str | None]=shutil.which, extra_ro: Any=(), shared_loopback_netns: bool=False, *args, **kwargs) -> dict[str, Any]:
    """Produce jail input configuration for bubblewrap detonation."""
    bwrap_available = which_fn('bwrap') is not None
    jail_argv = []
    if bwrap_available:
        cmd = ['true']
        if isinstance(provision_artifact, (list, tuple)):
            cmd = list(provision_artifact)
        elif isinstance(provision_artifact, str):
            cmd = [provision_artifact]
        orig_which = shutil.which
        shutil.which = which_fn
        try:
            jail_argv = build_detonation_jail_argv(cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=extra_ro, shared_loopback_netns=shared_loopback_netns)
        except LiveRunnerError:
            bwrap_available = False
            jail_argv = []
        finally:
            shutil.which = orig_which
    return {'bwrap_available': bwrap_available, 'jail_argv': jail_argv, 'repo_root': repo_root, 'work_dir': work_dir}