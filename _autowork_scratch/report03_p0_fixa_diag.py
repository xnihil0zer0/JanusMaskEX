"""Diagnostic for INTEGRATION_REPORT_03 P0 fix(a): home= threading + mount reorder.

Proves two things the RED oracle must assert:
  (1) BYTE-IDENTITY when the agy pool is DISABLED: passing home=env['HOME']
      (which == os.environ['HOME'] when pool off) yields a jail argv byte-identical
      to the current no-home= call. => off-flag path == HEAD.
  (2) The mount-ordering bug when pool ENABLED: a slot HOME under repo_root has its
      rw-bind shadowed by the later repo ro-bind (current code binds home subdirs at
      ~:183-199, BEFORE the repo ro-bind at ~:332). The fix must ensure the slot-home
      rw-bind comes AFTER the repo ro-bind so the slot is writable.
"""
import os
from harness import agent_jail

cmd = ['agy', '-p', 'x']
opHOME = os.environ['HOME']

# (1) pool-OFF byte identity
a = agent_jail.build_jail_argv(cmd, repo_root='/tmp/repo_x', work_dir='/tmp/wd_x', state_dir='/tmp/sd_x')
b = agent_jail.build_jail_argv(cmd, repo_root='/tmp/repo_x', work_dir='/tmp/wd_x', state_dir='/tmp/sd_x', home=opHOME)
print('[1] pool-OFF byte-identity (a == b):', a == b)
assert a == b, 'OFF-FLAG NOT BYTE-IDENTICAL — RED oracle core assertion would fail'

# (2) demonstrate the shadow: when home is UNDER repo_root, the repo ro-bind index
#     currently comes AFTER the home rw-bind index => slot home shadowed read-only.
repo = '/tmp/repo_under'
slot_home = repo + '/.agents/agy-pool/w0'
os.makedirs(os.path.join(slot_home, '.gemini'), exist_ok=True)
argv = agent_jail.build_jail_argv(cmd, repo_root=repo, work_dir='/tmp/wd2', state_dir='/tmp/sd2', home=slot_home)
# find last index of repo ro-bind and the slot-home .gemini rw-bind
def last_bind_idx(av, mode, path):
    idxs = [i for i in range(len(av)-2) if av[i]==mode and av[i+1]==path]
    return max(idxs) if idxs else -1
repo_ro = last_bind_idx(argv, '--ro-bind', os.path.realpath(repo))
gem_rw = last_bind_idx(argv, '--bind', os.path.realpath(os.path.join(slot_home, '.gemini')))
print('[2] repo ro-bind idx:', repo_ro, ' slot .gemini rw-bind idx:', gem_rw)
print('[2] SHADOWED (repo ro-bind AFTER slot rw-bind => bug present):', repo_ro > gem_rw)
print('    (fix must move slot-home rw-bind to AFTER repo ro-bind so repo_ro < gem_rw)')
