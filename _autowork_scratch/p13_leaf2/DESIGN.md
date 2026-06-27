# P1.3 leaf-2 — make the bwrap detonation jail's loopback reach the host `LoopbackListener`

**Verdict: COMPLEX — design plan for owner review. Do NOT auto-author a brief.**

**Why not a brief:** the only correct fix edits `ngv2/poc_runner_live.py`, whose own module header
(lines 1–12) declares it **"OWNER-HAND-AUTHORED, irreducible-tier infrastructure … deliberately NOT
pipeline-built and NOT fuzz-verifiable"** because it `fork`/`execve`s an attacker-controlled PoC inside
the bwrap jail. The fix changes the jail's **network-isolation policy** — the single most security-
sensitive control in the detonation system — and is a genuine process-model restructure (a netns-owning
helper) spanning `poc_runner_live.py` + `workers/_runner.py` + a new helper, not a single red-pair. The
sibling `_default_pip_installer` is already called out in the acceptance contract (line 197) as needing
"a separate follow-on brief." This change belongs in the same owner-reviewed, hand-authored tier.

---

## 1. The defect (empirically confirmed)

`workers/_runner.py::_make_detonation_seam` (line 276) starts `LoopbackListener(host='127.0.0.1', port=0)`
in the **host** network namespace. `poc_runner_live.py::build_detonation_jail_argv` (line 82) builds the
real jail with `--unshare-net`, which gives the PoC a **fresh, isolated** netns. Inside it, `127.0.0.1`
is the *jail's own* loopback stack — a different stack from the host's. The nonce callback can never arrive.

**Probe B (host listener vs `--unshare-net` jailed client), on this host (bwrap 0.6.1):**
```
HOST_LISTENER_PORT 36077
JAILED_CLIENT_STDOUT: CLIENT_ERR URLError <urlopen error [Errno 111] Connection refused>
HOST_LISTENER_HITS: []          # zero hits — host listener unreachable from the jail
```

Leaf-1 (landed) only "proved" the channel via an **injected** `mock_jail_runner` that does the `urlopen`
*in-process* in the host netns (`tests/ngv2/test_wire_loopback_per_cwe_channels.py:78-86`). The real
`_default_jail_runner` (`poc_runner_live.py:386`) goes through `--unshare-net`, so a REAL jailed PoC's
127.0.0.1 callback is dropped. This is exactly the leaf-2 gap.

**Note on the contract's "loopback is up in-jail" claim (line 299):** TRUE but insufficient. bwrap 0.6.1
*does* bring `lo` up inside `--unshare-net` (Probe A: a server+client both *inside* one jail talk over
127.0.0.1 fine). The problem is not "lo is down"; it's that the **listener and the PoC are in two
different netns**. The fix must put them in the **same** isolated netns.

---

## 2. Options evaluated (each: outbound-blocked? feasible? FS-oracle intact?)

| # | Option | Loopback reaches listener? | Outbound blocked? | FS-snapshot oracle holds? | Feasibility / cost | Verdict |
|---|--------|---------------------------|-------------------|---------------------------|--------------------|---------|
| **a-naive** | Drop `--unshare-net`, run jail with `--share-net` (inherit **host** netns) so listener on host lo is reachable | yes | **NO — host netns = full network; exfil open** | yes | trivial | **REJECT — breaks the core containment guarantee** |
| **(a)** | Move the *listener* into the jail's netns | n/a (listener is host-side Python; can't bind into bwrap's child netns from the parent without a shared netns — collapses into (c)) | — | — | — | **subsumed by (c)** |
| **(b)** | Abstract-namespace UNIX socket / socket-bridge passed into the jail | yes (if bound + FD-passed) | yes | yes | requires the *PoC payload* to speak a UNIX socket, but real SSRF sinks emit **HTTP to an IP:port** — payload bank `CWE-918` is `http://127.0.0.1:<<PORT>>/<<NONCE>>`. A UNIX socket changes the attacker-facing contract and won't match real sinks. | **REJECT — wrong wire protocol for SSRF** |
| **(c)** | **Shared isolated netns**: one fresh userns+netns, `lo` up, the listener bound *inside it*, the jail joins it via `--unshare-all --share-net` | **YES** | **YES** | YES | moderate — a netns-owning helper subprocess | **RECOMMEND** |
| **(d)** | slirp-style userspace net (slirp4netns / pasta) | yes | configurable, but **default gives OUTBOUND** | yes | heavy new dependency; default-on outbound is the opposite of what we want | **REJECT — new dep + outbound-by-default** |

### Recommended: (c) shared isolated netns — empirically validated end-to-end

A dedicated **netns-owning helper subprocess** does all of: create a fresh `CLONE_NEWUSER|CLONE_NEWNET`
namespace, bring `lo` up, bind the `LoopbackListener` *inside* it, then run the jailed PoC with bwrap
`--unshare-all --share-net` so the jail **joins that same netns**. 127.0.0.1 is now one shared stack
(callback works); the netns has only `lo` (no outbound); the parent runner keeps full host network.

**Probe G (the realizable production process model):**
```
PARENT_NET_BEFORE: True
CHILD_RESULT: {"hits": ["/abc_NONCE"]}     # nonce arrived at the in-netns listener
PARENT_NET_AFTER:  True                     # parent host network UNTOUCHED (pip fallback intact)
```
**Probe F (same netns, outbound check):** `LOOPBACK 200` AND `OUTBOUND_BLOCKED OSError` — a raw-IP
connect to `1.1.1.1:80` fails (no DNS confound). **Outbound stays blocked.**
**Probe H:** the in-netns listener still writes its `fs_signature` sentinel into the shared `work_dir`
and the parent sees it — **netns isolation is orthogonal to the mount/FS namespace, so the FS-snapshot
oracle is unaffected.**
**Probe J1:** `lo` can be brought up with a pure-Python `ioctl(SIOCSIFFLAGS, IFF_UP)` — **no dependency
on the `ip` binary** (which may be absent from the jail / minimal hosts).

---

## 3. Security blast-radius analysis (the load-bearing part)

**Net change to isolation: TIGHTER, not looser.** Today `--unshare-net` = fully isolated netns with `lo`.
Option (c) = a fully isolated netns with `lo` that the *host listener also lives in*. The PoC still has
**only loopback**; there is still **no route off-host**.

- **Outbound exfil:** STAYS BLOCKED. Proven (Probe F): raw-IP outbound from the jailed PoC fails. The
  shared netns contains `lo` only — no `eth*`, no default route, no NAT, no slirp.
- **The host listener is the *only* new reachable peer**, and it is a fixed, owner-authored HTTP handler
  (`loopback_listener.py`) that only records the request path and writes a sentinel. The PoC cannot reach
  any *other* host service (the host's real loopback services live in the **host** netns, which the jail
  does NOT join — that's the whole point of using a *fresh* netns rather than `--share-net` on the host).
- **Credential bind invariant (contract line 181):** UNCHANGED. The fix only swaps the netns flag; it adds
  **no** `--bind`/`--ro-bind` of `~/.gemini`/`~/.claude`/`$HOME`. The mount profile is identical.
- **userns requirement:** the helper needs unprivileged `CLONE_NEWUSER`+`CLONE_NEWNET` (Probe E:
  `UNPRIV_USERNS_NETNS=OK`, `max_user_namespaces=384810` on this host). bwrap already relies on
  unprivileged user namespaces, so this is the same trust assumption already in force.
- **Fail-closed:** if userns/netns creation fails (locked-down host), the helper must **refuse** (raise
  `LiveRunnerError`) rather than fall back to host-netns `--share-net` — never silently widen the net.
  Equally, if `lo` cannot be brought up, refuse. (A non-SSRF detonation that needs no callback could still
  run under the existing `--unshare-net` path; the shared-netns path is taken only when a listener is in play.)
- **Residual risk:** the helper runs the listener with elevated (root-in-userns) effective privileges to
  set `lo` up. Keep the listener handler exactly as-is (no shell-out, no file read of attacker-named paths
  beyond the bounded sentinel write inside `work_dir`). The PoC never shares the listener's process — it's
  a separate bwrap child — so a PoC RCE cannot reach the listener's address space.

---

## 4. Recommended implementation shape (for the owner-authored change)

1. **`poc_runner_live.py`:** add a `build_detonation_jail_argv(..., *, share_net: bool=False)` knob.
   When `share_net=True`, emit `--unshare-all --share-net` (inherit the caller's netns) **instead of**
   `--unshare-net`; keep every other flag identical. Add a netns-owning helper
   `run_in_shared_loopback_netns(listener_factory, run_jailed)` that: forks a child →
   `unshare(CLONE_NEWUSER|CLONE_NEWNET)` → write `setgroups deny` + `uid_map`/`gid_map` → bring `lo` up via
   `ioctl(SIOCSIFFLAGS, IFF_UP|IFF_RUNNING)` (Probe J1) → start the listener in-netns → invoke the jailed
   PoC with `share_net=True` → report `(hits, run_result)` back to the parent over a pipe. Fail-closed on
   any namespace error.
2. **`workers/_runner.py::_make_detonation_seam`:** instead of starting the listener host-side and calling
   `detonate_live` separately, route the SSRF/loopback path through the helper so the listener and jail
   share one netns. Preserve the existing `jail_runner=` injection seam for unit tests.
3. **Leave the non-callback CWE paths on the existing `--unshare-net` path** (no listener → no shared netns
   needed), so RCE/path-trav/code-inj detonations are unchanged.

**Same-file collision note:** P1.2 (`detonation.py`) runs in parallel; this leaf touches
`poc_runner_live.py` + `workers/_runner.py`, not `detonation.py` — no collision.

---

## 5. Test strategy (for the owner-authored change)

The decisive, **non-stub** assertion the leaf-1 oracle lacks:

- **Positive (the real thing):** run a REAL jailed PoC (a tiny `urllib.request.urlopen(NGV2_SSRF_CALLBACK)`)
  through the production `_default_jail_runner` / shared-netns helper (NOT an injected mock that urlopens
  in-process), `skipif not bwrap_available()`. Assert `nonce ∈ listener.hits` (and ∉ a baseline run with no
  callback). This is what fails today and would pass after the fix.
- **Outbound-still-blocked:** the same real jailed PoC additionally attempts a **raw-IP** outbound connect
  (e.g. to a fixed RFC-5737 TEST-NET address like `192.0.2.1:80`, which never routes anywhere) and asserts
  it FAILS — proving the fix did not widen the net. (Use a TEST-NET address, never a real internet IP, for
  determinism and to avoid any real egress.)
- **FS-oracle no-regression:** an RCE fixture that touches the `expected_fs_signature` still confirms via
  the snapshot diff (the existing `test_legacy_fs_effect_verdict_regression` pattern).
- **Negative:** a safe fixture issues no callback → `received(nonce)` False → refused.
- **Fail-closed:** with namespace creation forced to fail, assert `LiveRunnerError` (never a host-netns
  fallback).

Determinism: importlib loading; no `uuid`/`random`/clock-derived values in assertions; fixed sentinels;
nonces are the existing deterministic `ssrf_<finding_id>` derivation (already proven in leaf-1's
`test_nonce_derivation_determinism`); no `*_TOKEN`/`_SECRET`/`_KEY`/`_PASSWORD`/`_CRED` identifiers.

---

## 6. Simple-vs-complex summary

- **Simple part:** the argv knob (`share_net` → `--unshare-all --share-net`) is a few lines.
- **Complex part:** the netns-owning helper + the `_runner.py` process-model restructure (listener and jail
  co-located in one isolated netns, results piped back, fail-closed), **inside an explicitly
  owner-hand-authored, security-sensitive, not-pipeline-built module** that governs the jail's network
  isolation. That combination is why this is COMPLEX and owner-gated.

## 7. Recommendation (3 sentences)

Adopt **option (c)**: a netns-owning helper subprocess that creates one fresh isolated userns+netns, brings
`lo` up, binds the host `LoopbackListener` *inside it*, and runs the jailed PoC with `--unshare-all
--share-net` so the SSRF callback reaches the listener over a shared loopback while outbound stays blocked
(all four properties empirically confirmed: callback arrives, outbound refused, FS-snapshot oracle intact,
parent host network untouched). Because the fix edits the owner-hand-authored, irreducible `poc_runner_live.py`
and changes the jail's load-bearing network-isolation policy, it should be implemented as an
**owner-reviewed hand-authored change** (or an explicitly owner-gated brief with a pre-authored decision
file), not an auto-authored pipeline brief. Key risk to front-load: the helper MUST fail-closed on any
namespace-creation failure rather than degrade to host-netns `--share-net`, which would silently reopen
outbound exfil.
