/* Run with Node; no npm dependencies. Exercises user consent and async failures. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/challenge-suggest.js'), 'utf8');
class Element {
  constructor() { this.value = ''; this.children = []; this.events = {}; this.hidden = true; this.checked = false; }
  addEventListener(name, callback) { (this.events[name] ||= []).push(callback); }
  async fire(name) { for (const callback of this.events[name] || []) await callback(); }
  dispatchEvent(event) { void this.fire(event.type); }
  append(...elements) { this.children.push(...elements); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  removeAttribute() {}
  reportValidity() { return true; }
}
const suggestion = {title: 'AI title', problem: 'AI problem', objectives: 'AI objectives', deliverables: '<script>text only</script>'};
function boot() {
  const ids = Object.fromEntries(['challenge-ai', 'challenge-ai-button', 'challenge-ai-status',
    'challenge-ai-preview', 'challenge-ai-proposals', 'challenge-ai-apply', 'challenge-ai-dismiss'].map(id => [id, new Element()]));
  const fields = Object.fromEntries(['title', 'problem', 'objectives', 'deliverables', 'track', 'idea', 'audience', 'duration', 'csrfmiddlewaretoken'].map(name => [name, new Element()]));
  for (const [name, element] of Object.entries(fields)) element.id = 'id_' + name;
  fields.idea.value = 'An idea'; fields.track.value = '1'; fields.csrfmiddlewaretoken.value = 'fake-test-csrf';
  const form = new Element();
  form.elements = {namedItem: name => fields[name]};
  form.querySelector = selector => ({textContent: selector});
  const box = ids['challenge-ai'];
  box.closest = () => form;
  box.dataset = {url: '/suggest/', busy: 'busy', error: 'error', done: 'done', changed: 'changed', review: 'review', kept: 'kept'};
  let reply = async () => ({ok: true, json: async () => ({...suggestion})});
  const calls = [];
  const context = {document: {getElementById: id => ids[id], createElement: () => new Element(), createTextNode: text => text},
    URLSearchParams, AbortController, Event, setTimeout, clearTimeout,
    fetch: async (...args) => { calls.push(args); return reply(); }};
  vm.runInNewContext(source, context);
  const run = () => ids['challenge-ai-button'].fire('click');
  const checkboxes = () => ids['challenge-ai-proposals'].children.map(row => row.children[0].children[0]);
  return {ids, fields, form, calls, run, checkboxes, reply: fn => { reply = fn; }};
}
(async () => {
  let app = boot();
  await app.run();
  for (const name of Object.keys(suggestion)) assert.equal(app.fields[name].value, suggestion[name]);
  assert.equal(app.ids['challenge-ai-preview'].hidden, true);
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0][1].headers['X-CSRFToken'], 'fake-test-csrf');
  assert.equal(app.calls[0][1].body.get('track'), '1');

  app = boot(); app.fields.title.value = 'My title'; app.fields.problem.value = 'My problem';
  await app.run();
  assert.equal(app.fields.title.value, 'My title');
  assert.equal(app.fields.problem.value, 'My problem');
  assert.equal(app.fields.objectives.value, suggestion.objectives);
  assert.equal(app.ids['challenge-ai-apply'].disabled, true);
  const [title, problem] = app.checkboxes();
  title.checked = true; await title.fire('change');
  assert.equal(app.ids['challenge-ai-apply'].disabled, false);
  await app.ids['challenge-ai-apply'].fire('click');
  assert.equal(app.fields.title.value, suggestion.title);
  assert.equal(app.fields.problem.value, 'My problem');
  assert.equal(app.ids['challenge-ai-preview'].hidden, true);

  app = boot(); app.fields.title.value = 'My title';
  await app.run();
  const consent = app.checkboxes()[0]; consent.checked = true; await consent.fire('change');
  app.fields.title.value = 'Edited after selecting'; await app.fields.title.fire('input');
  assert.equal(consent.checked, false);
  assert.equal(app.ids['challenge-ai-apply'].disabled, true);
  await app.ids['challenge-ai-dismiss'].fire('click');
  assert.equal(app.fields.title.value, 'Edited after selecting');
  assert.equal(app.ids['challenge-ai-status'].textContent, 'kept');

  app = boot();
  app.reply(async () => {
    app.fields.track.value = '2';
    return {ok: true, json: async () => ({...suggestion})};
  });
  await app.run();
  assert.equal(app.fields.title.value, '');
  assert.equal(app.ids['challenge-ai-status'].textContent, 'changed');

  for (const reply of [async () => { throw Error('network'); }, async () => ({ok: false, json: async () => ({error: 'quota'})}),
    async () => ({ok: true, json: async () => ({title: 42})}), async () => ({ok: false, json: async () => { throw Error('HTML login'); }})]) {
    app = boot(); app.fields.title.value = 'Keep this'; app.reply(reply);
    await app.run();
    assert.equal(app.fields.title.value, 'Keep this');
    assert.equal(app.fields.problem.value, '');
    assert.equal(app.ids['challenge-ai-button'].disabled, false);
  }
  console.log('M1 assistant: empty fields, selective consent, edited fields, changed context and failures passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
