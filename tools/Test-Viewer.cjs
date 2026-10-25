// Exercise the embedded viewer's request/cancellation behavior without hardware.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { performance } = require('node:perf_hooks');

const source = fs.readFileSync(path.join(__dirname, '../firmware/SynchroCam/SynchroCam.ino'), 'utf8');
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const elements = Object.fromEntries(['video', 'start', 'stop', 'hint', 'status'].map(id => [id, {
  style: {}, disabled: true, textContent: '',
  removeAttribute(name) { delete this[name]; }
}]));
const events = {};
const urls = new Set();
let serial = 0, requests = 0, active = 0, maxActive = 0, aborts = 0;
let hang = false, decodeMs = 2;

function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    const aborted = () => { clearTimeout(timer); aborts++; reject(new Error('Aborted')); };
    const timer = ms === null ? null : setTimeout(() => {
      signal.removeEventListener('abort', aborted); resolve();
    }, ms);
    signal.addEventListener('abort', aborted, { once: true });
    if (signal.aborted) aborted();
  });
}

const document = {
  hidden: false,
  querySelector: selector => elements[selector.slice(1)],
  addEventListener: (name, callback) => { events[name] = callback; }
};
const context = vm.createContext({
  document, window: { addEventListener: (name, callback) => { events[name] = callback; } },
  performance, AbortController,
  setTimeout: (callback, ms) => setTimeout(callback, ms === 2500 ? 80 : ms),
  clearTimeout,
  URL: {
    createObjectURL: () => { const url = 'blob:' + ++serial; urls.add(url); return url; },
    revokeObjectURL: url => { urls.delete(url); }
  },
  Image: class { decode() { return wait(decodeMs); } },
  fetch: async (url, options) => {
    if (url === '/status') return { json: async () => ({ camera_ready: true, sensor: '0x3660', width: 320, height: 240 }) };
    assert.equal(url, '/capture');
    assert.equal(options.cache, 'no-store');
    requests++; active++; maxActive = Math.max(maxActive, active);
    try { await pause(hang ? null : 5, options.signal); }
    catch (error) { active--; throw error; }
    return {
      ok: true,
      blob: async () => {
        try { await pause(5, options.signal); return {}; }
        finally { active--; }
      }
    };
  }
});

(async () => {
  vm.runInContext(script, context);
  await wait(0);
  assert.equal(elements.start.disabled, false);
  let run = elements.start.onclick();
  await wait(230);
  assert.ok(requests >= 3, 'Live view should continue requesting frames');
  assert.equal(maxActive, 1, 'Only one image request should be in flight');
  assert.equal(urls.size, 1, 'Keep only the currently displayed object URL');
  elements.stop.onclick();
  await run;
  const stoppedCount = requests;
  await wait(90);
  assert.equal(requests, stoppedCount, 'Stop must prevent further requests');
  assert.equal(urls.size, 0, 'Stop must release the displayed image');

  hang = true;
  const abortsBeforeTimeout = aborts;
  run = elements.start.onclick();
  await wait(120);
  assert.ok(aborts > abortsBeforeTimeout, 'A stalled fetch must time out');
  assert.match(elements.hint.textContent, /retrying/);
  hang = false;
  await wait(480);
  assert.ok(elements.video.src, 'Viewer must recover after a stalled request');
  elements.stop.onclick();
  await run;

  decodeMs = 110;
  run = elements.start.onclick();
  await wait(30);
  elements.stop.onclick();
  await run;
  assert.equal(elements.video.src, undefined, 'Late image decoding must not restart a stopped viewer');
  assert.equal(urls.size, 0, 'Cancelled decoding must release its object URL');

  decodeMs = 2; hang = true;
  const oldRun = elements.start.onclick();
  await wait(10);
  elements.stop.onclick();
  hang = false;
  const newRun = elements.start.onclick();
  await wait(70);
  document.hidden = true;
  events.visibilitychange();
  await Promise.all([oldRun, newRun]);
  assert.equal(active, 0);
  assert.equal(maxActive, 1, 'Rapid Stop/Start must cancel the previous fetch');
  assert.equal(urls.size, 0);
  assert.match(elements.hint.textContent, /Paused/);
  console.log('PASS: sequential image requests, stop, timeout/recovery, late decode, rapid restart, hidden-page cleanup.');
})().catch(error => { console.error(error); process.exitCode = 1; });
