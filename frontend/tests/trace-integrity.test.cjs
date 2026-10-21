const test = require('node:test');
const assert = require('node:assert/strict');
global.window = { location: { href: 'https://trace.test/trace.html' } };
global.document = { readyState: 'loading', getElementById: () => ({}), addEventListener: () => {} };
const { classifyIntegrity } = require('../js/trace.js');
const valid = { batch_code: 'LOT', is_valid: true, status: 'VERIFIED', total_events_checked: 4,
  total_batches_checked: 1, verification_seal: 'a'.repeat(64) };

test('valid evidence for the displayed batch permits VERIFIED', () => {
  assert.equal(classifyIntegrity(valid, 'LOT'), 'VERIFIED');
});
test('missing, empty or mismatched evidence never permits VERIFIED', () => {
  for (const result of [null, {}, {...valid, batch_code: 'OTHER'}, {...valid, total_events_checked: 0},
    {...valid, verification_seal: ''}, {...valid, is_valid: undefined}]) {
    assert.equal(classifyIntegrity(result, 'LOT'), 'UNAVAILABLE');
  }
});
test('tampered-chain response is shown as INVALID', () => {
  assert.equal(classifyIntegrity({...valid, is_valid: false, status: 'HASH_MISMATCH'}, 'LOT'), 'INVALID');
});

async function renderWithIntegrity(integrity) {
  const vm = require('node:vm');
  const fs = require('node:fs');
  const path = require('node:path');
  const nodes = new Map();
  const node = () => ({textContent: '', hidden: false, replaceChildren() {}, appendChild() {}});
  const document = {readyState: 'complete', createElement: node, getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, node());
    return nodes.get(id);
  }};
  const window = {location: {href: 'http://trace.local/trace.html?batch_code=LOT', origin: 'http://trace.local'},
    AGRITRACE_CONFIG: {apiBase: 'http://trace.local'}, setTimeout, clearTimeout};
  const fetch = async url => {
    url = String(url);
    if (url.endsWith('/integrity')) {
      if (integrity instanceof Error) throw integrity;
      return {ok: true, json: async () => integrity};
    }
    return {ok: true, json: async () => ({batch_code: 'LOT', product_name: 'Produce',
      recall_warning: true, recall_message: 'CẢNH BÁO THU HỒI', origin: {}, milestones: [], root_batches: []})};
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../js/trace.js'), 'utf8'),
    {document, window, fetch, URL, AbortController});
  await new Promise(setImmediate);
  return nodes;
}

test('page renders VERIFIED without hiding the independent Recall warning', async () => {
  const nodes = await renderWithIntegrity(valid);
  assert.match(nodes.get('integrity-status').textContent, /^Dữ liệu đã được xác thực/);
  assert.equal(nodes.get('recall-warning').hidden, false);
});
test('page renders INVALID for a failed chain check', async () => {
  const nodes = await renderWithIntegrity({...valid, is_valid: false, status: 'HASH_MISMATCH'});
  assert.match(nodes.get('integrity-status').textContent, /^Dữ liệu không toàn vẹn/);
});
test('page renders unavailable when the integrity request fails', async () => {
  const nodes = await renderWithIntegrity(new Error('Network unavailable'));
  assert.match(nodes.get('integrity-status').textContent, /^Chưa thể xác minh dữ liệu/);
});

test('formatVnDateTime formats UTC timestamp into Vietnam local time (UTC+7)', () => {
  const { formatVnDateTime, formatVnDate } = require('../js/trace.js');
  // 15:44:07 UTC -> 22:44:07 ICT (UTC+7)
  const formatted = formatVnDateTime('2026-10-20T15:44:07.688932');
  assert.equal(formatted, '20/10/2026 22:44:07');

  // Date format
  assert.equal(formatVnDate('2026-10-19'), '19/10/2026');
  assert.equal(formatVnDateTime(''), '');
  assert.equal(formatVnDate(''), '');
});
