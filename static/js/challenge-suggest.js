/* Suggestions only change form values. Saving always uses the ordinary POST form. */
(function () {
  'use strict';
  const box = document.getElementById('challenge-ai');
  if (!box) return;
  const form = box.closest('form');
  const field = name => form.elements.namedItem(name);
  const button = document.getElementById('challenge-ai-button');
  const status = document.getElementById('challenge-ai-status');
  const preview = document.getElementById('challenge-ai-preview');
  const proposals = document.getElementById('challenge-ai-proposals');
  const apply = document.getElementById('challenge-ai-apply');
  const names = ['title', 'problem', 'objectives', 'deliverables'];
  const inputs = ['track', 'idea', 'audience', 'duration'];
  const context = () => inputs.map(name => field(name).value).join('\u0000');
  let pending = [];
  let controller;
  button.hidden = false;

  function updateConsent() { apply.disabled = !pending.some(item => item.checkbox.checked); }

  function dismiss() {
    pending = [];
    proposals.replaceChildren();
    preview.hidden = true;
    updateConsent();
  }
  function fill(name, value) {
    field(name).value = value;
    field(name).dispatchEvent(new Event('input', { bubbles: true }));
  }
  inputs.forEach(name => field(name).addEventListener('input', () => {
    dismiss();
    status.textContent = box.dataset.changed;
  }));
  names.forEach(name => field(name).addEventListener('input', () => {
    const item = pending.find(item => item.name === name);
    if (item) item.checkbox.checked = false; // Editing a field revokes earlier replacement consent.
    updateConsent();
  }));
  document.getElementById('challenge-ai-dismiss').addEventListener('click', () => {
    dismiss();
    status.textContent = box.dataset.kept;
  });
  apply.addEventListener('click', () => {
    if (apply.disabled) return;
    pending.forEach(item => {
      if (item.checkbox.checked) fill(item.name, item.value);
    });
    dismiss();
    status.textContent = box.dataset.done;
  });
  form.addEventListener('submit', () => { if (controller) controller.abort(); });
  button.addEventListener('click', async () => {
    for (const name of inputs) {
      if (!field(name).reportValidity()) return;
    }
    dismiss();
    const originalContext = context();
    const body = new URLSearchParams(inputs.map(name => [name, field(name).value]));
    controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    button.disabled = true;
    box.setAttribute('aria-busy', 'true');
    status.textContent = box.dataset.busy;
    try {
      const response = await fetch(box.dataset.url, {
        method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: { 'X-CSRFToken': field('csrfmiddlewaretoken').value, 'Accept': 'application/json' }, body
      });
      const data = await response.json();
      if (!response.ok) { status.textContent = data.error || box.dataset.error; return; }
      if (names.some(name => typeof data[name] !== 'string' || !data[name].trim())) throw new Error();
      if (context() !== originalContext) { status.textContent = box.dataset.changed; return; }
      names.forEach(name => {
        if (!field(name).value.trim()) { fill(name, data[name]); return; }
        if (field(name).value === data[name]) return;
        const row = document.createElement('div');
        const label = document.createElement('label');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.addEventListener('change', updateConsent);
        label.append(checkbox, document.createTextNode(' ' + form.querySelector('label[for="' + field(name).id + '"]').textContent));
        const text = document.createElement('pre');
        text.textContent = data[name];
        row.append(label, text);
        proposals.append(row);
        pending.push({ name, value: data[name], checkbox });
      });
      preview.hidden = !pending.length;
      status.textContent = pending.length ? box.dataset.review : box.dataset.done;
    } catch (_) {
      status.textContent = box.dataset.error;
    } finally {
      clearTimeout(timer);
      button.disabled = false;
      box.removeAttribute('aria-busy');
    }
  });
}());
