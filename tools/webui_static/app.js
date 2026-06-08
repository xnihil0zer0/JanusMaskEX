// JanusMask WebUI v2 — single-page operator console.
// Vanilla ES2022. Hash-routed pages. SSE for live state.
"use strict";

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
const TOKEN_KEY = "janusmask.operator_token";

function getToken() {
  // 1) ?token=… in URL takes precedence and persists
  const url = new URL(window.location.href);
  const fromQuery = url.searchParams.get("token");
  if (fromQuery) {
    localStorage.setItem(TOKEN_KEY, fromQuery);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url);
  }
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}

async function api(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  const token = getToken();
  if (token) headers.set("X-Operator-Token", token);
  if (["POST", "PUT", "DELETE"].includes(opts.method || "GET")) {
    const nonceRes = await fetch("/api/csrf", { headers });
    if (nonceRes.ok) {
      const { nonce } = await nonceRes.json();
      headers.set("X-CSRF-Nonce", nonce);
    }
    if (opts.body && typeof opts.body !== "string") {
      headers.set("Content-Type", "application/json");
      opts.body = JSON.stringify(opts.body);
    }
  }
  const res = await fetch(path, { ...opts, headers });
  let body = null;
  try { body = await res.json(); } catch {}
  if (!res.ok) {
    toast(`${opts.method || "GET"} ${path} → ${res.status} ${body?.error || ""}`, "err");
  }
  return { status: res.status, body };
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

// ---------------------------------------------------------------------------
// SSE store
// ---------------------------------------------------------------------------
const store = {
  state: null,
  recentEvents: [],
  streams: { claude: [], gemini: [] },
  parseFailures: 0,
  subscribers: new Set(),
};
function notify() { store.subscribers.forEach((fn) => fn()); }

// ---------------------------------------------------------------------------
// AW9d: transient per-slug badge overlays for the brief panel.
// Populated by the SSE tail handler when one of the three new ledger event
// types (plan_kickoff / extract / planner_hallucination_discarded) arrives;
// consulted in pages.briefs render to override the pill text/style for the
// matching row. Entries expire after 30s (plan_kickoff, extract) or 60s
// (planner_hallucination_discarded) and are removed lazily on read.
// ---------------------------------------------------------------------------
const transientBriefBadges = new Map();
const TRANSIENT_BADGE_EVENTS = new Set([
  "plan_kickoff",
  "extract",
  "planner_hallucination_discarded",
]);
const TRANSIENT_BADGE_TTL_MS = {
  plan_kickoff: 30000,
  extract: 30000,
  planner_hallucination_discarded: 60000,
};
const TRANSIENT_BADGE_COLOR = {
  plan_kickoff: "goldenrod",
  extract: "steelblue",
  planner_hallucination_discarded: "firebrick",
};

function _extractBriefSlug(raw) {
  if (raw == null) return "";
  let v = String(raw).trim();
  if (!v) return "";
  const slashIdx = v.lastIndexOf("/");
  if (slashIdx >= 0) v = v.slice(slashIdx + 1);
  if (v.startsWith("brief_hooks_")) v = v.slice("brief_hooks_".length);
  if (v.endsWith(".md")) v = v.slice(0, -3);
  return v.trim();
}

function _recordTransientBriefBadge(line) {
  if (!line || typeof line !== "object") return;
  const evt = line.event;
  if (typeof evt !== "string" || !TRANSIENT_BADGE_EVENTS.has(evt)) return;
  const slug = _extractBriefSlug(line.detail || line.task_id || line.slug || "");
  if (!slug) return;
  const ttl = TRANSIENT_BADGE_TTL_MS[evt] || 30000;
  transientBriefBadges.set(slug, { kind: evt, expiry: Date.now() + ttl });
}

function startSSE() {
  const es = new EventSource("/events");
  es.addEventListener("tail", (e) => {
    try {
      const data = JSON.parse(e.data);
      const path = data.path || "";
      let line = null;
      try { line = JSON.parse(data.line); } catch { line = { raw: data.line }; }
      if (path.includes("claude_stream.jsonl"))      store.streams.claude.push(line);
      else if (path.includes("gemini_stream.jsonl")) store.streams.gemini.push(line);
      else                                           store.recentEvents.push({ path, ...line });
      // AW9d: populate per-slug transient badge overlays from ledger events.
      _recordTransientBriefBadge(line);
      // bound buffers
      for (const k of ["claude", "gemini"]) {
        if (store.streams[k].length > 500) store.streams[k] = store.streams[k].slice(-500);
      }
      if (store.recentEvents.length > 200) store.recentEvents = store.recentEvents.slice(-200);
      notify();
    } catch (err) { /* swallow */ }
  });
  es.addEventListener("server-shutdown", () => toast("server shutting down", "warn"));
  es.onerror = () => { toast("SSE disconnected; retrying…", "warn"); };
}

async function refreshState() {
  const { status, body } = await api("/api/state");
  if (status === 200 && body) {
    store.state = body;
    store.parseFailures = 0;
    notify();
  } else if (status === 503) {
    store.parseFailures++;
    if (store.parseFailures > 3) toast("STATE.json unavailable", "warn");
  }
}

// ---------------------------------------------------------------------------
// Top-bar status + orchestrator buttons
// ---------------------------------------------------------------------------
function renderTopbar() {
  const s = store.state || {};
  const phase = s.phase || "idle";
  const taskId = s.task_id || "—";
  const orchPill = document.getElementById("orch-status");
  const phasePill = document.getElementById("phase-pill");
  const taskPill = document.getElementById("task-pill");
  phasePill.textContent = "phase: " + phase;
  taskPill.textContent = "task: " + taskId;
  if (phase === "idle") { orchPill.className = "pill status-unknown"; orchPill.textContent = "orchestrator: idle"; }
  else                  { orchPill.className = "pill status-running"; orchPill.textContent = "orchestrator: " + phase; }
}

function wireOrchestratorButtons() {
  const handlers = {
    "orch-start":  "/api/orchestrator/start",
    "orch-stop":   "/api/orchestrator/stop",
    "orch-pause":  "/api/orchestrator/pause",
    "orch-resume": "/api/orchestrator/resume",
  };
  for (const [id, path] of Object.entries(handlers)) {
    document.getElementById(id).addEventListener("click", async () => {
      const { status, body } = await api(path, { method: "POST", body: {} });
      if (status === 200) toast(`${id.replace("orch-", "")} → ${body?.status || "ok"}`, "ok");
      refreshState();
    });
  }
}

// ---------------------------------------------------------------------------
// Autowork topbar: pill + 3 buttons + 5s status poll.
// ---------------------------------------------------------------------------
let autoworkPollHandle = null;
let lastAutoworkStatus = null;

async function refreshAutoworkStatus() {
  const pill = document.getElementById("autowork-status");
  const pauseBtn = document.getElementById("autowork-pause");
  const { status, body } = await api("/api/autowork/status");
  if (status !== 200 || !body || typeof body !== "object") {
    lastAutoworkStatus = null;
    if (pill) { pill.className = "pill status-unknown"; pill.textContent = "autowork: ?"; }
    if (pauseBtn) pauseBtn.textContent = "⏸ pause";
    return;
  }
  lastAutoworkStatus = body;
  if (!pill) return;
  const alive = !!body.alive;
  const paused = !!body.paused;
  const cap = Number.isFinite(body.cap) ? body.cap : 0;
  const running = Array.isArray(body.running_jobs) ? body.running_jobs.length : 0;
  let cls;
  let text;
  if (!alive) {
    cls = "status-stopped";
    text = "autowork: stopped";
  } else if (paused) {
    cls = "status-paused";
    text = "autowork: paused";
  } else {
    cls = "status-running";
    text = `autowork: running ${running}/${cap}`;
  }
  pill.className = "pill " + cls;
  pill.textContent = text;
  if (pauseBtn) pauseBtn.textContent = paused ? "▶ resume" : "⏸ pause";
}

function wireAutoworkButtons() {
  document.getElementById("autowork-start")?.addEventListener("click", async () => {
    const { status, body } = await api("/api/autowork/start", { method: "POST", body: {} });
    if (status === 200) toast(`autowork: ${body?.status || "ok"}`, "ok");
    refreshAutoworkStatus();
  });
  document.getElementById("autowork-stop")?.addEventListener("click", async () => {
    const { status, body } = await api("/api/autowork/stop", { method: "POST", body: {} });
    if (status === 200) toast(`autowork: ${body?.status || "ok"}`, "ok");
    refreshAutoworkStatus();
  });
  document.getElementById("autowork-pause")?.addEventListener("click", async () => {
    const path = (lastAutoworkStatus && lastAutoworkStatus.paused)
      ? "/api/autowork/resume"
      : "/api/autowork/pause";
    const { status, body } = await api(path, { method: "POST", body: {} });
    if (status === 200) toast(`autowork: ${body?.status || "ok"}`, "ok");
    refreshAutoworkStatus();
  });
}

function startAutoworkPolling() {
  if (autoworkPollHandle !== null) return;
  refreshAutoworkStatus();
  autoworkPollHandle = setInterval(refreshAutoworkStatus, 5000);
}

function stopAutoworkPolling() {
  if (autoworkPollHandle !== null) {
    clearInterval(autoworkPollHandle);
    autoworkPollHandle = null;
  }
}

window.addEventListener("beforeunload", stopAutoworkPolling);
window.addEventListener("pagehide", stopAutoworkPolling);

// ---------------------------------------------------------------------------
// Autobrief helpers (F3): localStorage agent persistence + CSRF nonce fetch
// for the manual fetch path needed to attach an AbortSignal.
// ---------------------------------------------------------------------------
const AUTOBRIEF_AGENT_KEY = "autobrief_agent";

function readAutobriefAgent() {
  try {
    const v = localStorage.getItem(AUTOBRIEF_AGENT_KEY);
    if (v === "claude" || v === "gemini") return v;
  } catch (_) { /* localStorage missing or denied -> default */ }
  return "claude";
}

function writeAutobriefAgent(v) {
  if (v !== "claude" && v !== "gemini") return;
  try { localStorage.setItem(AUTOBRIEF_AGENT_KEY, v); } catch (_) { /* silent */ }
}

async function fetchCsrfNonce() {
  const headers = new Headers();
  const tk = getToken();
  if (tk) headers.set("X-Operator-Token", tk);
  try {
    const res = await fetch("/api/csrf", { headers });
    if (!res.ok) return "";
    const j = await res.json();
    return j.nonce || "";
  } catch (_) { return ""; }
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------
const pages = {};

pages.dashboard = async () => {
  await refreshState();
  const s = store.state || {};
  return `
    <h2>Dashboard</h2>
    <div class="row">
      <div class="col card">
        <h3>Current state</h3>
        <table>
          <tr><th>phase</th><td>${s.phase || "—"}</td></tr>
          <tr><th>task_id</th><td>${s.task_id || "—"}</td></tr>
          <tr><th>round</th><td>${s.round ?? "—"}</td></tr>
          <tr><th>claude</th><td>${s.claude_status || "—"} ${s.claude_pid ? "(pid " + s.claude_pid + ")" : ""}</td></tr>
          <tr><th>gemini</th><td>${s.gemini_status || "—"} ${s.gemini_pid ? "(pid " + s.gemini_pid + ")" : ""}</td></tr>
          <tr><th>cross-exam</th><td>${s.cross_exam_round ?? 0}</td></tr>
        </table>
      </div>
      <div class="col card">
        <h3>Recent events</h3>
        <pre>${escape(store.recentEvents.slice(-12).reverse().map((r) =>
          `${r.ts || ""} ${r.event || r.kind || "?"} ${r.task_id || ""}`).join("\n"))}</pre>
      </div>
    </div>`;
};

pages.briefs = async () => {
  const { body } = await api("/api/briefs/status");
  // S1 (session #26): surface per-brief autowork eligibility from
  // /api/autowork/status.eligibility (eligible[] + blocked[{slug,reason}]).
  const { body: awBody } = await api("/api/autowork/status");
  const elig = (awBody && awBody.eligibility && typeof awBody.eligibility === "object" && !awBody.eligibility.error)
    ? awBody.eligibility
    : null;
  const eligibleSet = new Set(elig ? (elig.eligible || []) : []);
  const blockedMap = new Map();
  if (elig) for (const blk of (elig.blocked || [])) blockedMap.set(blk.slug, blk.reason);
  const parkedMap = (elig && elig.parked && typeof elig.parked === "object") ? elig.parked : {};
  const eligBadge = (slug) => {
    if (!elig) return `<span class="pill status-stopped" title="eligibility unavailable">—</span>`;
    if (eligibleSet.has(slug)) return `<span class="pill status-running" title="eligible for autowork">eligible</span>`;
    const reason = blockedMap.get(slug);
    if (reason === "stale") return `<span class="pill status-blocked" title="brief older than max_age_sec">blocked: stale</span>`;
    if (reason === "not_in_allowlist") return `<span class="pill status-stopped" title="slug not in auto_promote.allowlist">blocked: not allowlisted</span>`;
    return `<span class="pill status-stopped" title="${escape(String(reason || "blocked"))}">blocked${reason ? ": " + escape(String(reason)) : ""}</span>`;
  };
  const stateClass = {
    complete: "status-running",
    in_flight: "status-paused",
    queued: "status-queued",
    blocked: "status-blocked",
    planned: "status-stopped",
    unplanned: "status-stopped",
  };
  const now = Date.now();
  const items = (body?.briefs || []).map((b) => {
    const n_accepted = (b.accepted || []).length;
    const n_total = (b.task_ids || []).length;
    const n_remaining = (b.remaining || []).length;
    const n_in_flight = n_total - n_accepted - n_remaining;
    const state = b.state;
    const cls = stateClass[state] || "status-stopped";
    let pillText;
    if (state === "complete")       pillText = "complete";
    else if (state === "in_flight") pillText = `${n_accepted}/${n_total}, ${n_in_flight} in flight`;
    else if (state === "queued")    pillText = `${n_accepted}/${n_total}, ${n_remaining} pending`;
    else if (state === "blocked")   pillText = "blocked";
    else if (state === "planned")   pillText = "planned (0 tasks)";
    else if (state === "unplanned") pillText = "no plan";
    else                            pillText = String(state ?? "");
    // AW9d: consult the transient badge map and override the pill when a
    // plan_kickoff / extract / planner_hallucination_discarded ledger event
    // is still within its decay window for this slug.
    let pillStyle = "";
    const transient = transientBriefBadges.get(b.slug);
    if (transient) {
      if (transient.expiry > now) {
        pillText = transient.kind;
        const color = TRANSIENT_BADGE_COLOR[transient.kind] || "goldenrod";
        pillStyle = ` style="background:${color};color:#fff;border-color:${color};"`;
      } else {
        transientBriefBadges.delete(b.slug);
      }
    }
    return `<tr>
      <td><a href="#/briefs/${escape(b.slug)}">${escape(b.slug)}</a></td>
      <td><span class="pill ${cls}"${pillStyle}>${escape(pillText)}</span></td>
      <td>${eligBadge(b.slug)}${(parkedMap[b.slug] && parkedMap[b.slug].length)
        ? ` <span class="pill status-blocked" title="task(s) parked in processed/ unaccepted — zombie">zombie: ${parkedMap[b.slug].length} parked</span>`
        : ""}</td>
      <td>${n_accepted}/${n_total}</td>
      <td>${tsfmt(b.mtime)}</td>
    </tr>`;
  }).join("");
  return `
    <style>
      .status-queued  { background: rgba(88,166,255,0.15); color: var(--accent); border-color: var(--accent); }
      .status-blocked { background: rgba(248,81,73,0.15);  color: var(--err);    border-color: var(--err); }
    </style>
    <h2>Briefs</h2>
    <div class="card" id="autowork-eligibility-summary">
      <h3>Autowork eligibility</h3>
      ${elig
        ? `<p>
            <span class="pill status-running">${elig.eligible_count ?? eligibleSet.size} eligible</span>
            <span class="pill status-queued">${(elig.dispatchable || []).length} dispatchable</span>
            <span class="pill status-blocked">${elig.blocked_count ?? blockedMap.size} blocked</span>
            <span class="muted">allowlist ${elig.allowlist_present
              ? `present (${(elig.allowlist_slugs || []).length} slug(s))`
              : "absent — deny-all (nothing dispatches)"}; max_age ${Math.round((elig.max_age_sec || 0) / 86400)}d</span>
          </p>`
        : `<p class="muted">eligibility unavailable${awBody && awBody.eligibility && awBody.eligibility.error
            ? ": " + escape(String(awBody.eligibility.error))
            : ""}</p>`}
    </div>
    <div class="card">
      <button class="btn primary" id="brief-new">+ new brief</button>
    </div>
    <div class="card"><table>
      <thead><tr><th>slug</th><th>state</th><th>autowork</th><th>accepted/total</th><th>modified</th></tr></thead>
      <tbody>${items || `<tr><td colspan="5" class="muted">no briefs found</td></tr>`}</tbody>
    </table></div>`;
};

pages["briefs/edit"] = async (slug) => {
  let initial = "";
  if (slug && slug !== "_new") {
    const { body } = await api(`/api/briefs/${slug}`);
    initial = body?.content || "";
  }
  const savedAgent = readAutobriefAgent();

  setTimeout(() => {
    // ----- Agent toggle persistence ----------------------------------------
    const toggleRoot = document.getElementById("brief-agent-toggle");
    if (toggleRoot) {
      toggleRoot.querySelectorAll("input[name='brief-agent']").forEach((el) => {
        el.addEventListener("change", () => {
          if (el.checked) writeAutobriefAgent(el.value);
        });
      });
    }

    // ----- Existing action handlers ----------------------------------------
    document.getElementById("brief-validate")?.addEventListener("click", async () => {
      const s = document.getElementById("brief-slug").value;
      await api(`/api/briefs/${s}/validate`, { method: "POST", body: {} }).then(({ body }) => {
        if (body?.valid) toast("brief valid", "ok");
        else toast(`invalid: ${(body?.stderr_tail || "").slice(0, 200)}`, "err");
      });
    });
    document.getElementById("brief-save")?.addEventListener("click", async () => {
      const s = document.getElementById("brief-slug").value;
      const c = document.getElementById("brief-content").value;
      const { status } = await api(`/api/briefs?force=1`, { method: "POST", body: { slug: s, content: c } });
      if (status === 200) toast("saved", "ok");
    });
    document.getElementById("brief-kickoff")?.addEventListener("click", async () => {
      const s = document.getElementById("brief-slug").value;
      if (!confirm(`Kick off planner against brief_hooks_${s}.md? This spawns Claude+Gemini and consumes API quota.`)) return;
      const { status, body } = await api(`/api/planner/kickoff`, { method: "POST", body: { brief_slug: s } });
      if (status === 200) toast(`planner started: job ${body.job_id}`, "ok");
    });

    // ----- Autocomplete (F3) -----------------------------------------------
    const ACTION_IDS = ["brief-validate", "brief-save", "brief-kickoff", "brief-autocomplete"];

    const setActionsDisabled = (disabled) => {
      ACTION_IDS.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !!disabled;
      });
      document.querySelectorAll("#brief-agent-toggle input[name='brief-agent']").forEach((el) => {
        el.disabled = !!disabled;
      });
    };

    let abortCtrl = null;
    let tickHandle = null;
    let leaveListener = null;

    const cleanupRequestState = () => {
      if (tickHandle !== null) {
        clearInterval(tickHandle);
        tickHandle = null;
      }
      if (leaveListener) {
        window.removeEventListener("hashchange", leaveListener);
        leaveListener = null;
      }
    };

    document.getElementById("brief-autocomplete")?.addEventListener("click", async () => {
      const acBtn = document.getElementById("brief-autocomplete");
      const contentEl = document.getElementById("brief-content");
      const slugEl = document.getElementById("brief-slug");
      if (!acBtn || !contentEl || !slugEl) return;

      const roughDraft = contentEl.value || "";
      const slugHint = slugEl.value || "";
      const byteLen = new TextEncoder().encode(roughDraft).length;
      const needsConfirm = byteLen > 4096 || slugHint.trim() !== "";
      if (needsConfirm) {
        const msg = "Overwrite the current brief content and slug with an auto-completed draft?";
        if (!window.confirm(msg)) return;
      }

      const selected = document.querySelector("#brief-agent-toggle input[name='brief-agent']:checked");
      const agent = (selected && selected.value) || "claude";

      const originalLabel = acBtn.textContent;
      let elapsed = 0;
      acBtn.innerHTML = `<span class="autobrief-spinner" aria-hidden="true"></span><span class="autobrief-elapsed" id="brief-autocomplete-elapsed">0s</span>`;
      tickHandle = setInterval(() => {
        elapsed += 1;
        const ctr = document.getElementById("brief-autocomplete-elapsed");
        if (ctr) ctr.textContent = elapsed + "s";
      }, 1000);
      setActionsDisabled(true);

      abortCtrl = new AbortController();
      leaveListener = () => {
        try { abortCtrl && abortCtrl.abort(); } catch (_) { /* ignore */ }
        cleanupRequestState();
      };
      // {once: true} so it auto-removes if it fires; we also remove it manually on completion.
      window.addEventListener("hashchange", leaveListener, { once: true });

      const nonce = await fetchCsrfNonce();
      const headers = new Headers();
      const tk = getToken();
      if (tk) headers.set("X-Operator-Token", tk);
      if (nonce) headers.set("X-CSRF-Nonce", nonce);
      headers.set("Content-Type", "application/json");

      let res = null;
      let body = null;
      let aborted = false;
      try {
        res = await fetch("/api/briefs/autocomplete", {
          method: "POST",
          headers,
          body: JSON.stringify({ rough_draft: roughDraft, agent, slug_hint: slugHint }),
          signal: abortCtrl.signal,
        });
        try { body = await res.json(); } catch (_) { body = null; }
      } catch (err) {
        if (err && (err.name === "AbortError" || abortCtrl.signal.aborted)) {
          aborted = true;
        } else {
          cleanupRequestState();
          setActionsDisabled(false);
          acBtn.textContent = originalLabel;
          toast(`autocomplete failed: ${err && err.message ? err.message : err}`, "err");
          return;
        }
      }

      // Always tear down timers + leave-listener before we touch the DOM.
      cleanupRequestState();

      if (aborted) {
        // Page is being torn down; do not restore UI or surface a toast.
        return;
      }

      setActionsDisabled(false);
      acBtn.textContent = originalLabel;

      if (res && res.status === 200 && body) {
        if (typeof body.content === "string") contentEl.value = body.content;
        if (typeof body.slug === "string" && body.slug.length) slugEl.value = body.slug;
        const validation = body.validation || {};
        if (validation.ok) {
          toast("autocomplete: validation ok", "ok");
        } else {
          const stderr = String(validation.stderr || "");
          const card = document.createElement("div");
          card.className = "toast err";
          const head = document.createElement("div");
          head.textContent = "autocomplete: validation failed";
          card.appendChild(head);
          const det = document.createElement("details");
          det.className = "autobrief-validation-details";
          const sm = document.createElement("summary");
          sm.textContent = "stderr";
          det.appendChild(sm);
          const pre = document.createElement("pre");
          pre.textContent = stderr;
          det.appendChild(pre);
          card.appendChild(det);
          document.getElementById("toasts").appendChild(card);
          setTimeout(() => card.remove(), 12000);
        }
      } else {
        const errMsg = (body && body.error) ? body.error : `HTTP ${res ? res.status : "?"}`;
        const detail = (body && body.detail) ? ` — ${body.detail}` : "";
        toast(`autocomplete: ${errMsg}${detail}`, "err");
      }
    });
  }, 0);

  const claudeChecked = savedAgent === "claude" ? " checked" : "";
  const geminiChecked = savedAgent === "gemini" ? " checked" : "";
  return `
    <h2>Brief: ${escape(slug || "(new)")}</h2>
    <div class="card">
      <input type="text" id="brief-slug" value="${escape(slug === "_new" ? "" : slug)}" placeholder="slug (a-z0-9_)" />
    </div>
    <div class="card" id="brief-agent-toggle" role="radiogroup" aria-label="Autobrief agent">
      <label class="pill"><input type="radio" name="brief-agent" value="claude"${claudeChecked} /> Claude</label>
      <label class="pill"><input type="radio" name="brief-agent" value="gemini"${geminiChecked} /> Gemini</label>
    </div>
    <div class="card">
      <textarea id="brief-content">${escape(initial)}</textarea>
    </div>
    <div class="card row">
      <button class="btn" id="brief-autocomplete" title="Auto-complete this draft via the selected agent">✨ Auto-complete</button>
      <button class="btn" id="brief-validate">Validate</button>
      <button class="btn primary" id="brief-save">Save</button>
      <button class="btn" id="brief-kickoff">▶ Kick off planner</button>
    </div>`;
};

// ---------------------------------------------------------------------------
// Autowork allowlist editor + orphan-endpoint handlers (session #25).
// All call the api() wrapper so X-Operator-Token + X-CSRF-Nonce are honored.
// ---------------------------------------------------------------------------
async function loadAutoworkAllowlist() {
  const ta = document.getElementById("autowork-allowlist-text");
  const statusEl = document.getElementById("autowork-allowlist-status");
  const { status, body } = await api("/api/autowork/allowlist");
  if (status === 200 && body) {
    const slugs = body.slugs || [];
    if (ta) ta.value = slugs.join("\n");
    if (statusEl) {
      statusEl.textContent = body.file_present
        ? `restricted to ${slugs.length} slug(s)`
        : "no allowlist file — deny-all (nothing dispatches)";
      statusEl.className = "muted";
    }
  }
  return { status, body };
}

async function saveAutoworkAllowlist() {
  const ta = document.getElementById("autowork-allowlist-text");
  const slugs = (ta ? ta.value : "")
    .split("\n").map((s) => s.trim()).filter(Boolean);
  const { status, body } = await api("/api/autowork/allowlist", {
    method: "PUT", body: { slugs },
  });
  if (status === 200) {
    toast(slugs.length
      ? `allowlist saved (${slugs.length} slug(s))`
      : "allowlist cleared — deny-all (nothing dispatches)", "ok");
    loadAutoworkAllowlist();
  }
  return { status, body };
}

async function extractPlanToQueue(planFilename, taskIds = "all") {
  const { status, body } = await api(
    "/api/plans/" + encodeURIComponent(planFilename) + "/extract",
    { method: "POST", body: { task_ids: taskIds, canonical: true } });
  if (status === 200) {
    const n = Array.isArray(body?.extracted) ? body.extracted.length : "?";
    toast(`extracted ${n} task(s) from ${planFilename}`, "ok");
  }
  return { status, body };
}

async function decideTaskApproval(taskId, decision) {
  // POST /api/tasks/<id>/approve  (or /reject or /retry)
  if (!["approve", "reject", "retry"].includes(decision)) return { status: 0, body: null };
  const { status, body } = await api(
    "/api/tasks/" + encodeURIComponent(taskId) + "/" + decision,
    { method: "POST", body: { reason: "via UI" } });
  if (status === 200) toast(`${decision} ${taskId}`, "ok");
  return { status, body };
}

async function killAgent(agentName) {
  const { status, body } = await api(
    "/api/agents/" + encodeURIComponent(agentName) + "/kill",
    { method: "POST", body: {} });
  if (status === 200) toast(`killed ${agentName}${body?.pid ? " (pid " + body.pid + ")" : ""}`, "ok");
  return { status, body };
}

async function updateConfigControl(controlBody) {
  const { status, body } = await api("/api/config/control",
    { method: "PUT", body: controlBody });
  if (status === 200) toast("control config saved", "ok");
  return { status, body };
}

pages.plans = async () => {
  const { body } = await api("/api/planner/current");
  const data = body?.plan || {};
  const tasks = data.tasks || [];
  const items = tasks.map((t) =>
    `<tr><td><input type="checkbox" class="plan-row-cb" value="${escape(t.task_id)}" /></td>
         <td>${escape(t.task_id)}</td><td>${escape(t.meta_task_type || "")}</td>
         <td>${escape(t.priority || "")}</td>
         <td>${(t.dependencies || []).join(", ") || "—"}</td></tr>`).join("");
  const planFile = body?.plan_file || "";
  if (planFile) {
    setTimeout(() => {
      document.getElementById("plan-extract-btn")?.addEventListener("click",
        () => extractPlanToQueue(planFile, "all"));
      document.getElementById("plan-extract-sel-btn")?.addEventListener("click",
        async () => {
          const ids = Array.from(document.querySelectorAll(".plan-row-cb"))
            .filter((cb) => cb.checked).map((cb) => cb.value);
          if (!ids.length) { toast("no tasks selected", "warn"); return; }
          await extractPlanToQueue(planFile, ids);
        });
    }, 0);
  }
  const extractCard = planFile
    ? `<div class="card"><button id="plan-extract-btn" class="btn primary">Extract all to queue</button>
         <button id="plan-extract-sel-btn" class="btn">Extract selected</button>
         <span class="muted"> → ${escape(planFile)}</span></div>`
    : "";
  return `
    <h2>Plans</h2>
    <div class="card muted">${planFile ? "Showing: " + escape(planFile) : "no plan loaded"}</div>
    ${extractCard}
    <div class="card"><table>
      <thead><tr><th></th><th>task_id</th><th>type</th><th>priority</th><th>depends_on</th></tr></thead>
      <tbody>${items}</tbody>
    </table></div>
    <div class="card"><h3>Dependency graph</h3>${dagSvg(tasks)}</div>`;
};

pages.tasks = async () => {
  setTimeout(() => {
    document.querySelectorAll(".tab-row button").forEach((btn) => {
      btn.addEventListener("click", () => location.hash = `#/tasks/${btn.dataset.partition}`);
    });
  }, 0);
  return `
    <h2>Tasks</h2>
    <div class="tab-row">
      <button data-partition="queued">queued</button>
      <button data-partition="processing">processing</button>
      <button data-partition="processed">processed</button>
      <button data-partition="blocked">blocked</button>
    </div>
    <p class="muted">Pick a partition above.</p>`;
};

pages["tasks/list"] = async (partition) => {
  const { body } = await api(`/api/tasks/${partition}`);
  // WUI-3: a non-accepting task now parks in processed/ or blocked/. Offer a
  // per-row Re-queue (POST /api/tasks/<id>/retry -> _maybe_requeue_task) so the
  // operator can recover a parked task without touching the filesystem.
  const canRequeue = (partition === "processed" || partition === "blocked");
  const canDecide = (partition === "processing");
  const items = (body?.items || []).map((it) => {
    const tid = String(it.name).replace(/\.json$/, "");
    let action = "";
    if (canRequeue) {
      action = `<button class="btn" data-requeue="${escape(tid)}">Re-queue</button>`;
    } else if (canDecide) {
      action = `<button class="btn primary" data-decide="approve" data-tid="${escape(tid)}">Approve</button>
                <button class="btn danger" data-decide="reject" data-tid="${escape(tid)}">Reject</button>`;
    }
    return `<tr><td>${escape(it.name)}</td><td>${tsfmt(it.mtime)}</td><td>${action}</td></tr>`;
  }).join("");
  if (canRequeue) {
    setTimeout(() => {
      document.querySelectorAll("[data-requeue]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await decideTaskApproval(btn.dataset.requeue, "retry");
          renderRoute();
        });
      });
    }, 0);
  }
  if (canDecide) {
    setTimeout(() => {
      document.querySelectorAll("[data-decide]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await decideTaskApproval(btn.dataset.tid, btn.dataset.decide);
          renderRoute();
        });
      });
    }, 0);
  }
  return `
    <h2>Tasks → ${partition}</h2>
    <div class="card"><table>
      <thead><tr><th>filename</th><th>mtime</th><th>action</th></tr></thead>
      <tbody>${items || `<tr><td colspan="3" class="muted">empty</td></tr>`}</tbody>
    </table></div>`;
};

pages.streams = async () => {
  const renderAgent = (agent) => {
    const events = store.streams[agent].slice(-50);
    return events.map((e) => streamCard(e)).join("");
  };
  setTimeout(() => {
    document.querySelectorAll("[data-kill-agent]").forEach((btn) => {
      btn.addEventListener("click", () => killAgent(btn.dataset.killAgent));
    });
  }, 0);
  return `
    <h2>Live agent streams</h2>
    <div class="row">
      <div class="col"><h3>Claude <button class="btn danger" data-kill-agent="claude">Kill</button></h3>${renderAgent("claude") || `<div class="muted">no events yet</div>`}</div>
      <div class="col"><h3>Gemini <button class="btn danger" data-kill-agent="gemini">Kill</button></h3>${renderAgent("gemini") || `<div class="muted">no events yet</div>`}</div>
    </div>`;
};

pages.approvals = async () => {
  // WUI-1c: a pending row is resolved once a later terminal event arrives for
  // the same task_id (HITL reject/approve emits phase_transition accepted/
  // rejected; task_terminal also closes it). Keep only the latest unresolved
  // pending_approval per task_id, in arrival order.
  const resolved = new Set();
  for (const e of store.recentEvents) {
    if (e.event === "task_terminal" && e.task_id) resolved.add(e.task_id);
    if (e.event === "phase_transition" && e.task_id &&
        (e.phase === "accepted" || e.phase === "rejected")) resolved.add(e.task_id);
  }
  const seen = new Set();
  const pending = store.recentEvents
    .filter((e) => e.event === "pending_approval" && e.task_id && !resolved.has(e.task_id))
    .filter((e) => { if (seen.has(e.task_id)) return false; seen.add(e.task_id); return true; });
  if (!pending.length) return `<h2>Approvals</h2><div class="card muted">No pending approvals.</div>`;
  setTimeout(() => {
    document.querySelectorAll("[data-decide]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const { task, decide: decision } = btn.dataset;
        await api(`/api/tasks/${task}/${decision}`, { method: "POST", body: { reason: "via UI" } });
        toast(`${decision} ${task}`, "ok");
        renderRoute();
      });
    });
  }, 0);
  return `<h2>Approvals</h2>` + pending.map((p) => `
    <div class="card">
      <h3>${escape(p.task_id)}</h3>
      <p>phase: <strong>${escape(p.detail || p.phase || "?")}</strong></p>
      <button class="btn primary" data-decide="approve" data-task="${escape(p.task_id)}">Approve</button>
      <button class="btn danger"  data-decide="reject"  data-task="${escape(p.task_id)}">Reject</button>
      <button class="btn"         data-decide="retry"   data-task="${escape(p.task_id)}">Retry</button>
    </div>`).join("");
};

pages.config = async () => {
  const { body } = await api("/api/config");
  // WUI-PHASES: populate the require_approval <select> from the single-source
  // GET /api/control/phases (control_gate.KNOWN_PHASES); fall back to the
  // literal if the endpoint is unavailable (the fallback also includes
  // ast_validation so it stays in sync with the server).
  const phasesResp = await api("/api/control/phases");
  const knownPhases = Array.isArray(phasesResp.body?.phases) && phasesResp.body.phases.length
    ? phasesResp.body.phases
    : ["synthesis","fuzzing","cross_examination","ast_validation","accepted","rejected","decomposition"];
  const cfg = body?.config || {};
  const aw = (cfg.autowork && typeof cfg.autowork === "object") ? cfg.autowork : {};
  let cap = parseInt(aw.parallel_cap, 10);
  if (!Number.isFinite(cap)) cap = 4;
  setTimeout(() => {
    const saveBtn = document.getElementById("autowork-cap-save");
    const inp = document.getElementById("autowork-cap-input");
    const msgEl = document.getElementById("autowork-cap-msg");
    if (!saveBtn || !inp) return;
    saveBtn.addEventListener("click", async () => {
      const raw = parseInt(inp.value, 10);
      if (msgEl) { msgEl.textContent = ""; msgEl.className = "muted"; }
      const { status, body: resp } = await api("/api/config/autowork", {
        method: "PUT",
        body: { parallel_cap: Number.isFinite(raw) ? raw : 4 },
      });
      if (status === 200 && resp) {
        const { body: refreshed } = await api("/api/config");
        const rcfg = refreshed?.config || {};
        const raw2 = rcfg.autowork && rcfg.autowork.parallel_cap;
        const parsed = parseInt(raw2, 10);
        if (Number.isFinite(parsed)) inp.value = String(parsed);
        if (resp.clamped && msgEl) {
          msgEl.textContent = `value clamped to ${Number.isFinite(parsed) ? parsed : "?"}`;
          msgEl.className = "warn";
        } else {
          toast("autowork: parallel_cap saved", "ok");
        }
      }
    });
    const hbBtn = document.getElementById("autowork-hb-save");
    const hbInp = document.getElementById("autowork-hb-input");
    if (hbBtn && hbInp) {
      hbBtn.addEventListener("click", async () => {
        const raw = parseInt(hbInp.value, 10);
        if (!Number.isFinite(raw) || raw < 1) { toast("heartbeat_sec must be a positive integer", "warn"); return; }
        const { status } = await api("/api/config/autowork", {
          method: "PUT", body: { heartbeat_sec: raw },
        });
        if (status === 200) toast("autowork: heartbeat_sec saved", "ok");
      });
    }
  }, 0);
  const ctrl = (cfg.control && typeof cfg.control === "object") ? cfg.control : {};
  setTimeout(() => {
    loadAutoworkAllowlist();
    document.getElementById("autowork-allowlist-save")?.addEventListener("click", saveAutoworkAllowlist);
    document.getElementById("autowork-allowlist-reload")?.addEventListener("click", loadAutoworkAllowlist);
    document.getElementById("ctrl-save")?.addEventListener("click", () => {
      const obj = {};
      const ra = document.getElementById("ctrl-require-approval");
      if (ra) obj.require_approval = Array.from(ra.selectedOptions).map((o) => o.value);
      const at = document.getElementById("ctrl-approval-timeout");
      if (at && at.value.trim() !== "") obj.approval_timeout_sec = parseInt(at.value, 10);
      const pf = document.getElementById("ctrl-pause-flag");
      if (pf && pf.value.trim() !== "") obj.pause_flag_path = pf.value.trim();
      const dd = document.getElementById("ctrl-decisions-dir");
      if (dd && dd.value.trim() !== "") obj.decisions_dir = dd.value.trim();
      updateConfigControl(obj);
    });
  }, 0);
  return `
    <h2>Config</h2>
    <div class="card">
      <h3>Autowork</h3>
      <label>Parallel cap:
        <input id="autowork-cap-input" type="number" min="1" max="16" step="1" value="${cap}" />
      </label>
      <button id="autowork-cap-save" class="btn primary">Save</button>
      <span id="autowork-cap-msg" class="muted"></span>
      <div style="margin-top:8px">
        <label>Heartbeat (sec):
          <input id="autowork-hb-input" type="number" min="1" step="1" value="${(aw.heartbeat_sec != null ? escape(String(aw.heartbeat_sec)) : "1800")}" />
        </label>
        <button id="autowork-hb-save" class="btn">Save</button>
        <span class="muted"> idle re-scan interval</span>
      </div>
    </div>
    <div class="card">
      <h3>Autowork allowlist</h3>
      <p class="muted">Empty = deny-all (nothing dispatches); listing slugs restricts the daemon to only those.</p>
      <textarea id="autowork-allowlist-text" rows="6" placeholder="one brief slug per line"></textarea>
      <div class="row">
        <button id="autowork-allowlist-save" class="btn primary">Save allowlist</button>
        <button id="autowork-allowlist-reload" class="btn">Reload</button>
        <span id="autowork-allowlist-status" class="muted"></span>
      </div>
    </div>
    <div class="card">
      <h3>Control (HITL)</h3>
      <label>require_approval (phases):
        <select id="ctrl-require-approval" multiple size="5">
          ${knownPhases.map((ph) =>
            `<option value="${ph}"${Array.isArray(ctrl.require_approval) && ctrl.require_approval.includes(ph) ? " selected" : ""}>${ph}</option>`).join("")}
        </select>
      </label>
      <label>approval_timeout_sec: <input type="number" id="ctrl-approval-timeout" value="${ctrl.approval_timeout_sec != null ? escape(String(ctrl.approval_timeout_sec)) : ""}" /></label>
      <label>pause_flag_path: <input type="text" id="ctrl-pause-flag" value="${ctrl.pause_flag_path != null ? escape(String(ctrl.pause_flag_path)) : ""}" /></label>
      <label>decisions_dir: <input type="text" id="ctrl-decisions-dir" value="${ctrl.decisions_dir != null ? escape(String(ctrl.decisions_dir)) : ""}" /></label>
      <button id="ctrl-save" class="btn primary">Save control</button>
    </div>
    <div class="card"><pre>${escape(JSON.stringify(cfg, null, 2))}</pre></div>
    <div class="card muted">PUT /api/config/control accepts: require_approval, approval_timeout_sec, pause_flag_path, decisions_dir.</div>`;
};

pages.activity = async () => {
  const events = store.recentEvents.slice(-50).reverse();
  const rows = events.map((r) => `<tr>
    <td>${escape(r.ts || "")}</td>
    <td>${escape(r.event || r.kind || "?")}</td>
    <td>${escape(r.phase || "")}</td>
    <td>${escape(r.task_id || "")}</td>
    <td>${escape(r.detail || "")}</td>
  </tr>`).join("");
  return `<h2>Activity log (recent SSE tail)</h2>
    <div class="card"><table>
      <thead><tr><th>ts</th><th>event</th><th>phase</th><th>task</th><th>detail</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5" class="muted">no events</td></tr>`}</tbody>
    </table></div>`;
};

// ---------------------------------------------------------------------------
// Chat panel (#/chat).
// Self-managed, append-only operator chat. The #chat-transcript container and
// the uncontrolled #chat-input control are NOT rebuilt on each SSE tick — the
// chatIsOpen() guard in boot()'s subscriber skips the live re-render while this
// route is open, so an in-progress message / transcript survives a live /events
// tick (mirrors the briefEditorIsOpen() clobber-guard precedent). #chat-resend
// re-sends the current transcript.
// ---------------------------------------------------------------------------
// Self-managed append-only chat state. Rendered from the synchronous POST
// response (the overseer runs the turn server-side and returns the assistant
// text); the buffer lets the transcript survive navigating away and back.
const overseerChat = { cid: null, mode: "observe", buffer: [] };
const OVERSEER_MODES = ["observe", "analyze", "audit", "dispatch", "brief-author"];

function _chatTurnNode(turn) {
  const div = document.createElement("div");
  const role = turn.role || "?";
  div.className = "chat-turn chat-turn-" + role;
  if (turn.mode) div.setAttribute("data-mode", turn.mode);
  div.innerHTML =
    `<span class="chat-role">${escape(role)}${turn.mode ? " · " + escape(turn.mode) : ""}</span>` +
    `<div class="chat-content"></div>`;
  div.querySelector(".chat-content").textContent = turn.content != null ? String(turn.content) : "";
  return div;
}

function pushChatTurn(turn) {
  overseerChat.buffer.push(turn);
  if (overseerChat.buffer.length > 500) overseerChat.buffer = overseerChat.buffer.slice(-500);
  const cont = document.getElementById("chat-transcript");
  if (cont) { cont.appendChild(_chatTurnNode(turn)); cont.scrollTop = cont.scrollHeight; }
}

function _chatPending(on) {
  const cont = document.getElementById("chat-transcript");
  if (!cont) return;
  const existing = cont.querySelector(".chat-pending");
  if (on && !existing) {
    const ph = document.createElement("div");
    ph.className = "chat-turn chat-turn-assistant chat-pending";
    ph.innerHTML = `<span class="chat-role">assistant · …</span><div class="chat-content">thinking…</div>`;
    cont.appendChild(ph);
    cont.scrollTop = cont.scrollHeight;
  } else if (!on && existing) {
    existing.remove();
  }
}

function _applyChatResult(status, res) {
  _chatPending(false);
  if (status === 200 && res) {
    if (res.conversation_id) overseerChat.cid = res.conversation_id;
    pushChatTurn({ role: "assistant", content: res.text || "(no output)", mode: overseerChat.mode });
  } else if (status === 403) {
    pushChatTurn({ role: "system", content: "overseer disabled — set overseer.enabled: true in harness/config.yaml and restart the server", mode: "" });
  } else {
    pushChatTurn({ role: "system", content: `error ${status}: ${(res && (res.error || res.detail)) || "request failed"}`, mode: "" });
  }
}

async function sendChat() {
  const input = document.getElementById("chat-input");
  const text = input ? input.value.trim() : "";
  if (!text) return;
  input.value = "";
  pushChatTurn({ role: "user", content: text, mode: overseerChat.mode });
  _chatPending(true);
  const body = { text };
  if (overseerChat.cid) body.conversation_id = overseerChat.cid;
  const { status, body: res } = await api("/api/chat/send", { method: "POST", body });
  _applyChatResult(status, res);
}

async function resendChat() {
  if (!overseerChat.cid) { toast("nothing to resend yet", "warn"); return; }
  _chatPending(true);
  const { status, body: res } = await api("/api/chat/resend", { method: "POST", body: { conversation_id: overseerChat.cid } });
  _applyChatResult(status, res);
}

async function setChatMode(mode) {
  overseerChat.mode = mode;
  if (!overseerChat.cid) return;  // applied on next send (boots the conversation)
  const { status, body: res } = await api("/api/chat/mode", { method: "PUT", body: { conversation_id: overseerChat.cid, mode } });
  if (status === 200 && res && res.ok) toast(`mode → ${res.current_mode}`, "ok");
  else if (status === 409) toast(`mode ${mode} is locked (Tier-S needs unlock)`, "warn");
}

function _wireChatPanel() {
  const cont = document.getElementById("chat-transcript");
  if (cont) { cont.innerHTML = ""; for (const t of overseerChat.buffer) cont.appendChild(_chatTurnNode(t)); cont.scrollTop = cont.scrollHeight; }
  document.getElementById("chat-send")?.addEventListener("click", sendChat);
  document.getElementById("chat-resend")?.addEventListener("click", resendChat);
  const input = document.getElementById("chat-input");
  input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendChat(); }
  });
  const sel = document.getElementById("chat-mode");
  if (sel) { sel.value = overseerChat.mode; sel.addEventListener("change", () => setChatMode(sel.value)); }
}

pages.chat = async () => {
  setTimeout(_wireChatPanel, 0);
  const opts = OVERSEER_MODES.map((m) => `<option value="${m}"${m === overseerChat.mode ? " selected" : ""}>${m}</option>`).join("");
  return `
    <h2>Chat <span class="muted" style="font-size:0.7em">overseer · default-OFF behind overseer.enabled</span></h2>
    <div class="card">
      <div id="chat-transcript" class="chat-transcript" aria-live="polite"></div>
    </div>
    <div class="card">
      <div class="row">
        <label>mode <select id="chat-mode" class="chat-mode">${opts}</select></label>
        <button id="chat-resend" class="btn">↻ Resend transcript</button>
      </div>
      <div class="row">
        <textarea id="chat-input" class="chat-input" placeholder="message…  (Ctrl/⌘+Enter to send)"></textarea>
        <button id="chat-send" class="btn primary">Send</button>
      </div>
    </div>`;
};

pages.rebuild = async () => {
  if (window._rebuildPoll) { clearInterval(window._rebuildPoll); window._rebuildPoll = null; }
  setTimeout(() => {
    document.getElementById("rebuild-begin")?.addEventListener("click", beginRebuild);
    refreshRebuildStatus();
    window._rebuildPoll = setInterval(refreshRebuildStatus, 4000);
  }, 0);
  return `<h2>Cleanroom Rebuild</h2>
    <div class="card">
      <p class="muted">Reconstruct a project BLIND into a fresh replicant repo. The source stays a read-only oracle; the autowork daemon completes the rebuild autonomously (allowlist-gated, resumable). Leave Modules blank to auto-discover, or list a slice to rebuild one module.</p>
      <div class="row"><label>Input project dir<br><input id="rebuild-input" type="text" size="64" placeholder="/home/xnihil0zer0/JanusMask  or  samples/widgets"></label></div>
      <div class="row"><label>Output replicant dir<br><input id="rebuild-output" type="text" size="64" placeholder="/home/xnihil0zer0/JanusMaskJR"></label></div>
      <div class="row"><label>Modules (optional, comma-sep)<br><input id="rebuild-modules" type="text" size="64" placeholder="harness/depth_validator.py"></label></div>
      <div class="row"><label>Test files (optional, comma-sep)<br><input id="rebuild-tests" type="text" size="64" placeholder="tests/test_depth_validator.py"></label></div>
      <div class="row"><label>Seed files (optional, comma-sep)<br><input id="rebuild-seeds" type="text" size="64" placeholder="harness/__init__.py"></label></div>
      <div class="row"><button id="rebuild-begin" class="btn primary">Begin Cleanroom Rebuild</button> <span id="rebuild-msg" class="muted"></span></div>
    </div>
    <div class="card">
      <h3>Rebuild jobs</h3>
      <table id="rebuild-table">
        <thead><tr><th>job</th><th>status</th><th>done</th><th>remaining</th><th>current unit</th><th>deps · venv</th><th>output</th><th>head</th></tr></thead>
        <tbody><tr><td colspan="8" class="muted">loading…</td></tr></tbody>
      </table>
      <p class="muted" id="rebuild-running"></p>
    </div>`;
};

async function beginRebuild() {
  const input_dir = document.getElementById("rebuild-input").value.trim();
  const output_dir = document.getElementById("rebuild-output").value.trim();
  const modules = document.getElementById("rebuild-modules").value.trim();
  const test_files = document.getElementById("rebuild-tests").value.trim();
  const seed_files = document.getElementById("rebuild-seeds").value.trim();
  const msg = document.getElementById("rebuild-msg");
  if (!input_dir || !output_dir) { if (msg) msg.textContent = "input and output dirs required"; return; }
  if (msg) msg.textContent = "starting…";
  const body = { input_dir, output_dir };
  if (modules) body.modules = modules;
  if (test_files) body.test_files = test_files;
  if (seed_files) body.seed_files = seed_files;
  const { status, body: res } = await api("/api/rebuild/start", { method: "POST", body });
  if (status === 200) {
    toast(`rebuild job ${res.job_id} started (${res.units} units, allowlisted)`, "ok");
    if (msg) msg.textContent = `job ${res.job_id}: ${res.units} units queued — daemon will reconstruct`;
    refreshRebuildStatus();
  } else if (msg) {
    msg.textContent = `error: ${res?.error || status} ${res?.detail || ""}`;
  }
}

async function refreshRebuildStatus() {
  const { status, body } = await api("/api/rebuild/status");
  if (status !== 200 || !body) return;
  const tbody = document.querySelector("#rebuild-table tbody");
  const rows = (body.jobs || []).map((j) => `<tr>
    <td>${escape(j.job_id)}</td>
    <td>${escape(j.status)}${j.complete ? " ✓" : ""}</td>
    <td>${escape(j.done)}/${escape(j.total)}</td>
    <td>${escape(j.remaining)}</td>
    <td>${escape(j.current || "—")}</td>
    <td title="${escape((j.dependencies || []).join(", "))}">${escape((j.dependencies || []).length)} dep${(j.dependencies || []).length === 1 ? "" : "s"} · venv ${j.venv_ready ? "✓" : "—"}</td>
    <td title="${escape(j.output_dir || "")}">${escape((j.output_dir || "").split("/").slice(-1)[0] || "—")}</td>
    <td>${escape((j.head_sha || "").slice(0, 9) || "—")}</td>
  </tr>`).join("");
  if (tbody) tbody.innerHTML = rows || `<tr><td colspan="8" class="muted">no jobs yet</td></tr>`;
  const run = document.getElementById("rebuild-running");
  if (run) run.textContent = (body.running && body.running.length)
    ? `running rebuild loop: ${body.running.join(", ")}`
    : "no rebuild loop currently running";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function tsfmt(t) {
  if (!t) return "—";
  const d = new Date((typeof t === "number" ? t : parseFloat(t)) * 1000);
  return d.toISOString().replace("T", " ").slice(0, 19);
}

function streamCard(e) {
  const t = e.type || "?";
  if (t === "system") return `<div class="stream-card system">[system] ${escape(e.subtype || "")}</div>`;
  if (t === "stream_event" && e.delta?.text) return `<div class="stream-card thinking">${escape(e.delta.text.slice(0,300))}</div>`;
  if (t === "assistant") {
    const text = (e.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
    return `<div class="stream-card assistant">${escape(text.slice(0,800))}</div>`;
  }
  if (t === "result") return `<div class="stream-card result">[result] tokens used: ${escape(e.usage?.output_tokens || "?")}</div>`;
  return `<div class="stream-card">${escape(JSON.stringify(e).slice(0,300))}</div>`;
}

function dagSvg(tasks) {
  if (!tasks.length) return `<div class="muted">no tasks to graph</div>`;
  // Simple top-down layout: order by topological depth.
  const idx = new Map(tasks.map((t, i) => [t.task_id, i]));
  const depth = new Map();
  const computeDepth = (tid, seen = new Set()) => {
    if (depth.has(tid)) return depth.get(tid);
    if (seen.has(tid)) return 0;
    seen.add(tid);
    const t = tasks[idx.get(tid)];
    if (!t || !t.dependencies?.length) { depth.set(tid, 0); return 0; }
    const d = 1 + Math.max(...t.dependencies.map((d) => computeDepth(d, seen)));
    depth.set(tid, d); return d;
  };
  tasks.forEach((t) => computeDepth(t.task_id));
  const byDepth = new Map();
  for (const t of tasks) {
    const d = depth.get(t.task_id) || 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d).push(t);
  }
  const layerH = 80, nodeW = 180, nodeH = 36;
  const maxLayer = Math.max(...byDepth.values().map((l) => l.length));
  const W = Math.max(800, maxLayer * (nodeW + 20));
  const H = (Math.max(...depth.values()) + 1) * layerH + 40;
  const positions = new Map();
  for (const [d, layer] of byDepth) {
    layer.forEach((t, i) => {
      const x = 20 + i * (nodeW + 20);
      const y = 20 + d * layerH;
      positions.set(t.task_id, { x, y });
    });
  }
  const edges = tasks.flatMap((t) =>
    (t.dependencies || []).map((dep) => {
      const a = positions.get(dep), b = positions.get(t.task_id);
      if (!a || !b) return "";
      const ax = a.x + nodeW / 2, ay = a.y + nodeH;
      const bx = b.x + nodeW / 2, by = b.y;
      return `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="#58a6ff" stroke-width="1"/>`;
    })).join("");
  const nodes = tasks.map((t) => {
    const p = positions.get(t.task_id);
    return `<g><rect x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="4"
      fill="#161b22" stroke="#30363d"/>
      <text x="${p.x + 8}" y="${p.y + 22}" fill="#c9d1d9" font-size="11">${escape(t.task_id)}</text>
    </g>`;
  }).join("");
  return `<svg class="dag-svg" width="${W}" height="${H}">${edges}${nodes}</svg>`;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
// T1: predicate for the brief editor route (#/briefs/_new or #/briefs/<slug>).
// Mirrors renderRoute()'s own hash parsing so the router and this guard agree
// on route shape. Keys on a truthy second segment (the slug), so the briefs
// LIST route (#/briefs) and every non-editor route return false — only the
// editor, whose uncontrolled #brief-slug / #brief-content fields hold unsaved
// operator input, is exempted from the live re-render.
function briefEditorIsOpen() {
  const hash = location.hash.replace(/^#/, "");
  const parts = hash.split("/").filter(Boolean);
  return parts[0] === "briefs" && Boolean(parts[1]);
}

// T2: predicate for the Config (#/config) and Rebuild (#/rebuild) form routes.
// Mirrors renderRoute()'s hash parsing exactly (leading '#' stripped, split on
// '/' filtering empties). Both pages hold uncontrolled form inputs (parallel
// cap / heartbeat / allowlist / control fields; rebuild input/output/modules/
// tests/seeds) that a live re-render would wipe mid-edit, so they are exempted
// alongside the brief editor. The Config page loads once and the Rebuild page
// keeps its own refreshRebuildStatus poll, so no live freshness is lost.
function configOrRebuildIsOpen() {
  const hash = location.hash.replace(/^#/, "");
  const parts = hash.split("/").filter(Boolean);
  return parts[0] === "config" || parts[0] === "rebuild";
}

// T3: predicate for the chat panel route (#/chat). Mirrors renderRoute()'s hash
// parsing exactly (leading '#' stripped, split on '/' filtering empties), in the
// same idiom as briefEditorIsOpen(). The chat page owns user-editable state —
// the uncontrolled #chat-input control and the self-managed append-only
// #chat-transcript — so a live SSE re-render would clobber an in-progress
// message / transcript; it is exempted from the live render alongside the brief
// editor and the config/rebuild forms.
function chatIsOpen() {
  const hash = location.hash.replace(/^#/, "");
  const parts = hash.split("/").filter(Boolean);
  return parts[0] === "chat";
}

async function renderRoute() {
  const hash = location.hash.replace(/^#/, "") || "/dashboard";
  const parts = hash.split("/").filter(Boolean);
  document.querySelectorAll("nav#nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.route === parts[0]));
  const page = document.getElementById("page");
  let html = "";
  try {
    if (parts[0] === "briefs" && parts[1]) html = await pages["briefs/edit"](parts[1]);
    else if (parts[0] === "tasks" && parts[1]) html = await pages["tasks/list"](parts[1]);
    else if (pages[parts[0] || "dashboard"]) html = await pages[parts[0] || "dashboard"]();
    else html = `<p class="muted">unknown route: ${escape(hash)}</p>`;
  } catch (err) {
    html = `<div class="card err">render error: ${escape(err.message || err)}</div>`;
  }
  page.innerHTML = html;
  if (parts[0] === "briefs" && !parts[1]) {
    document.getElementById("brief-new")?.addEventListener("click", () => { location.hash = "#/briefs/_new"; });
  }
  renderTopbar();
}

window.addEventListener("hashchange", renderRoute);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", async () => {
  if (!getToken()) {
    const dlg = document.getElementById("auth-dialog");
    dlg.showModal();
    document.getElementById("auth-save").addEventListener("click", () => {
      setToken(document.getElementById("auth-input").value.trim());
      dlg.close();
      boot();
    });
  } else {
    boot();
  }
});

async function boot() {
  wireOrchestratorButtons();
  wireAutoworkButtons();
  startSSE();
  store.subscribers.add(renderTopbar);
  // re-render the active page on every SSE tick (cheap: page handlers are pure render)
  let renderQueued = false;
  store.subscribers.add(() => {
    // T1: while the brief editor route is open, the uncontrolled #brief-slug /
    // #brief-content fields hold unsaved operator input; a live re-render here
    // would rebuild #page and discard it. Skip only this live render — the
    // renderTopbar subscriber, hashchange navigation, and the 5s poll are
    // untouched, so the topbar pills keep updating and other routes stay live.
    if (briefEditorIsOpen()) return;
    if (configOrRebuildIsOpen()) return;
    if (chatIsOpen()) return;
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(() => { renderQueued = false; renderRoute(); });
  });
  await refreshState();
  if (!location.hash) location.hash = "#/dashboard";
  await renderRoute();
  // Refresh state every 5s as a fallback for slow SSE
  setInterval(refreshState, 5000);
  // Autowork status pill polling (5s); cancelled on page unload.
  startAutoworkPolling();
}
