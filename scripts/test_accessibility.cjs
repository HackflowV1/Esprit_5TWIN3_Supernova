/* Run with Node: no npm dependencies. Cover blocked/corrupt device storage. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/accessibility-init.js'), 'utf8');
function boot(saved, blocked = false) {
  const attributes = {};
  const context = {window:{}, document:{documentElement:{setAttribute:(name,value) => { attributes[name] = value; }}}, localStorage:{getItem:() => { if (blocked) throw new Error('Storage disabled'); return saved; }}};
  vm.runInNewContext(script, context);
  return {api:context.window.HackFlowAccessibility, attributes};
}
for (const value of [null, 'broken JSON', 'null', '[]', '{"text":"injected","contrast":"false","colors":"unknown"}']) {
  const {api, attributes} = boot(value);
  assert.equal(api.get().text, 'normal');
  assert.equal(api.get().contrast, false);
  assert.equal(attributes['data-a11y-colors'], 'standard');
}
const blocked = boot(null, true);
assert.equal(blocked.api.get().motion, 'system');
const saved = boot('{"colors":"red-green","text":"extra-large","contrast":true,"focus":true,"motion":"reduce","spacing":true}');
assert.equal(saved.attributes['data-a11y-text'], 'extra-large');
assert.equal(saved.attributes['data-a11y-focus'], 'true');
const copy = saved.api.get(); copy.text = 'invalid';
assert.equal(saved.api.get().text, 'extra-large');
saved.api.apply(saved.api.defaults);
assert.equal(saved.attributes['data-a11y-contrast'], 'false');
assert.equal(saved.attributes['data-a11y-text'], 'normal');
console.log('Accessibility preference storage and fallback checks passed.');
