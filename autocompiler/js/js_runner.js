'use strict';
/*
 * autocompiler/js/js_runner.js -- JanusMask JS batch runner (Phase B).
 *
 * Usage: node js_runner.js <batch.json>
 *
 * The batch file is JSON: {"code": <CommonJS source whose module.exports is
 * the target function>, "inputs": [[...args], ...], "timeout_ms": <int>}.
 *
 * The parent process forks a child of itself (child_process.fork) tagged via
 * env JANUSMASK_JS_RUNNER_ROLE=worker and relays the batch over IPC. The
 * worker writes the candidate source to a temp file, require()s it, and calls
 * module.exports(...args) for each input IN ORDER, racing each call against a
 * per-input timeout. Exactly ONE JSON document {"results": [...]} is written
 * to FD 3 (never stdout). JS-only values (undefined/NaN/+-Infinity) are
 * sentinel-encoded recursively.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { fork } = require('child_process');

// Recursive sentinel codec -- mirror the tags of autocompiler/js/js_codec.py.
function encodeValue(v) {
  if (v === undefined) {
    return { __sentinel__: 'undefined' };
  }
  if (typeof v === 'number') {
    if (Number.isNaN(v)) {
      return { __sentinel__: 'NaN' };
    }
    if (v === Infinity) {
      return { __sentinel__: 'Infinity' };
    }
    if (v === -Infinity) {
      return { __sentinel__: '-Infinity' };
    }
    return v;
  }
  if (v === null) {
    return null;
  }
  if (Array.isArray(v)) {
    return v.map(encodeValue);
  }
  if (typeof v === 'object') {
    const out = {};
    for (const key of Object.keys(v)) {
      out[key] = encodeValue(v[key]);
    }
    return out;
  }
  return v;
}

function failure(message, timedOut) {
  return {
    success: false,
    value: null,
    error: message === undefined || message === null ? null : String(message),
    timed_out: Boolean(timedOut),
  };
}

const TIMEOUT_SENTINEL = Symbol('janusmask-timeout');

if (process.env.JANUSMASK_JS_RUNNER_ROLE === 'worker') {
  // ---- Worker role: evaluate the candidate per input. ----
  process.on('message', async (batch) => {
    const inputs = Array.isArray(batch && batch.inputs) ? batch.inputs : [];
    let timeoutMs = batch && batch.timeout_ms;
    if (typeof timeoutMs !== 'number' || timeoutMs <= 0) {
      timeoutMs = 5000;
    }

    const results = [];
    let fn = null;
    let loadError = null;

    const tmpFile = path.join(
      os.tmpdir(),
      'jm_js_candidate_' + process.pid + '_' + Date.now() + '.js');
    try {
      fs.writeFileSync(tmpFile, String((batch && batch.code) || ''), 'utf8');
      const mod = require(tmpFile);
      if (typeof mod === 'function') {
        fn = mod;
      } else {
        loadError = 'candidate module.exports is not a function';
      }
    } catch (err) {
      loadError = err && err.message ? err.message : String(err);
    }

    for (let i = 0; i < inputs.length; i++) {
      if (loadError !== null) {
        results.push(failure(loadError, false));
        continue;
      }
      const args = Array.isArray(inputs[i]) ? inputs[i] : [inputs[i]];
      let timer = null;
      try {
        const callPromise = Promise.resolve().then(() => fn(...args));
        const timeoutPromise = new Promise((resolve) => {
          timer = setTimeout(() => resolve(TIMEOUT_SENTINEL), timeoutMs);
        });
        const outcome = await Promise.race([callPromise, timeoutPromise]);
        if (timer !== null) {
          clearTimeout(timer);
          timer = null;
        }
        if (outcome === TIMEOUT_SENTINEL) {
          results.push(failure('timed out', true));
        } else {
          results.push({
            success: true,
            value: encodeValue(outcome),
            error: null,
            timed_out: false,
          });
        }
      } catch (err) {
        if (timer !== null) {
          clearTimeout(timer);
          timer = null;
        }
        const message = err && err.message ? err.message : String(err);
        results.push(failure(message, false));
      }
    }

    try {
      fs.unlinkSync(tmpFile);
    } catch (e) {
      // best-effort cleanup
    }

    process.send({ results });
    process.exit(0);
  });
} else {
  // ---- Parent role: parse the batch, fork the worker, enforce deadline. ----
  let batch = null;
  try {
    batch = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  } catch (err) {
    fs.writeSync(3, JSON.stringify({ results: [] }));
    process.exit(2);
  }

  const inputs = Array.isArray(batch.inputs) ? batch.inputs : [];
  let timeoutMs = batch.timeout_ms;
  if (typeof timeoutMs !== 'number' || timeoutMs <= 0) {
    timeoutMs = 5000;
  }

  const batchDeadlineMs = timeoutMs * Math.max(1, inputs.length) + 5000;

  const child = fork(__filename, [], {
    env: Object.assign({}, process.env, { JANUSMASK_JS_RUNNER_ROLE: 'worker' }),
    stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
  });

  let done = false;
  function finish(results) {
    if (done) {
      return;
    }
    done = true;
    try {
      child.kill('SIGKILL');
    } catch (e) {
      // ignore
    }
    fs.writeSync(3, JSON.stringify({ results }));
    process.exit(0);
  }

  function fullFailureBatch() {
    const rows = [];
    for (let i = 0; i < inputs.length; i++) {
      rows.push(failure('worker did not report a result', false));
    }
    return rows;
  }

  const reaper = setTimeout(() => {
    finish(fullFailureBatch());
  }, batchDeadlineMs);

  child.on('message', (msg) => {
    clearTimeout(reaper);
    let results = msg && Array.isArray(msg.results) ? msg.results.slice() : [];
    while (results.length < inputs.length) {
      results.push(failure('missing worker result', false));
    }
    if (results.length > inputs.length) {
      results = results.slice(0, inputs.length);
    }
    finish(results);
  });

  child.on('exit', () => {
    if (!done) {
      clearTimeout(reaper);
      finish(fullFailureBatch());
    }
  });

  child.send({ code: batch.code, inputs: inputs, timeout_ms: timeoutMs });
}
