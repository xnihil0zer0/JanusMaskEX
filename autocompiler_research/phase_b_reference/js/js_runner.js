// js_runner.js -- JanusMask autocompiler JS batch runner (Phase B, ac-js-runner).
//
// Usage: node js_runner.js <batch.json>
//   batch.json: {"code": "<CommonJS source, module.exports = fn>",
//                "inputs": [[...args], ...], "timeout_ms": <int>}
//
// Evaluates the candidate in a forked child (child_process.fork) so a wedged
// candidate can be killed wholesale, races every call against the timeout via
// Promise.race, and writes ONE JSON document to FD 3 -- never stdout, which
// belongs to candidate console noise:
//   {"results": [{"success", "value", "error", "timed_out"}, ...]}
// JS-only values are sentinel-encoded: undefined/NaN/Infinity/-Infinity as
// {"__sentinel__": "<tag>"}.
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { fork } = require('child_process');

function encodeValue(v) {
  if (v === undefined) return { __sentinel__: 'undefined' };
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return { __sentinel__: 'NaN' };
    if (v === Infinity) return { __sentinel__: 'Infinity' };
    if (v === -Infinity) return { __sentinel__: '-Infinity' };
    return v;
  }
  if (Array.isArray(v)) return v.map(encodeValue);
  if (v && typeof v === 'object') {
    const out = {};
    for (const k of Object.keys(v)) out[k] = encodeValue(v[k]);
    return out;
  }
  return v === null ? null : v;
}

function failure(message, timedOut) {
  return { success: false, value: null, error: message, timed_out: !!timedOut };
}

// ---------------------------------------------------------------------------
// Child role: evaluate the candidate and run inputs, reporting per-input
// results back over the fork IPC channel.
// ---------------------------------------------------------------------------
if (process.env.JANUSMASK_JS_RUNNER_ROLE === 'worker') {
  process.on('message', async (batch) => {
    const results = [];
    let fn = null;
    let loadError = null;
    try {
      const tmp = path.join(os.tmpdir(),
        'jm_js_candidate_' + process.pid + '_' + Date.now() + '.js');
      fs.writeFileSync(tmp, String(batch.code), 'utf8');
      fn = require(tmp);
      if (typeof fn !== 'function') {
        loadError = 'module.exports is not a function';
      }
    } catch (err) {
      loadError = String(err && err.stack ? err.message : err);
    }
    const timeoutMs = Number(batch.timeout_ms) > 0 ? Number(batch.timeout_ms) : 5000;
    for (const args of batch.inputs) {
      if (loadError) {
        results.push(failure('candidate load failed: ' + loadError, false));
        continue;
      }
      let timer = null;
      try {
        const timeoutSentinel = Symbol('timeout');
        const timeoutPromise = new Promise((resolve) => {
          timer = setTimeout(() => resolve(timeoutSentinel), timeoutMs);
        });
        const value = await Promise.race([
          Promise.resolve().then(() => fn(...args)),
          timeoutPromise,
        ]);
        clearTimeout(timer);
        if (value === timeoutSentinel) {
          results.push(failure('per-input timeout after ' + timeoutMs + 'ms', true));
        } else {
          results.push({ success: true, value: encodeValue(value), error: null, timed_out: false });
        }
      } catch (err) {
        if (timer) clearTimeout(timer);
        results.push(failure(String(err && err.message !== undefined ? err.message : err), false));
      }
    }
    process.send({ results });
    process.exit(0);
  });
} else {
  // -------------------------------------------------------------------------
  // Parent role: fork the worker, relay the batch, enforce the wholesale
  // batch deadline, write results to FD 3.
  // -------------------------------------------------------------------------
  const batchPath = process.argv[2];
  let batch;
  try {
    batch = JSON.parse(fs.readFileSync(batchPath, 'utf8'));
  } catch (err) {
    fs.writeSync(3, JSON.stringify({ results: [] }));
    process.exit(2);
  }
  const inputs = Array.isArray(batch.inputs) ? batch.inputs : [];
  const timeoutMs = Number(batch.timeout_ms) > 0 ? Number(batch.timeout_ms) : 5000;
  // Wholesale ceiling: per-input budget for every input plus startup slack --
  // even a worker that ignores its own timers is reaped.
  const batchDeadlineMs = timeoutMs * Math.max(1, inputs.length) + 5000;

  const child = fork(__filename, [], {
    env: Object.assign({}, process.env, { JANUSMASK_JS_RUNNER_ROLE: 'worker' }),
    stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
  });

  let done = false;
  const finish = (results) => {
    if (done) return;
    done = true;
    try { child.kill('SIGKILL'); } catch (e) { /* already dead */ }
    fs.writeSync(3, JSON.stringify({ results }));
    process.exit(0);
  };

  const reaper = setTimeout(() => {
    finish(inputs.map(() => failure('batch deadline exceeded', true)));
  }, batchDeadlineMs);

  child.on('message', (msg) => {
    clearTimeout(reaper);
    const results = (msg && Array.isArray(msg.results)) ? msg.results : [];
    while (results.length < inputs.length) {
      results.push(failure('worker ended before producing a result', false));
    }
    finish(results);
  });
  child.on('exit', () => {
    if (!done) {
      clearTimeout(reaper);
      finish(inputs.map(() => failure('worker exited before reporting', false)));
    }
  });
  child.send({ code: batch.code, inputs, timeout_ms: timeoutMs });
}
