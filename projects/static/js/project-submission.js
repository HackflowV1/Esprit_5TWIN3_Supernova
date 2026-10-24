/* Progressive enhancement only; Django validates every submission server-side. */
(() => {
  for (const form of document.querySelectorAll('[data-deliverable-form]')) {
    const kind = form.querySelector('[name="kind"]');
    if (!kind) continue;
    const setRequired = (name, required) => {
      const input = form.querySelector(`[name="${name}"]`);
      if (!input) return;
      input.required = required;
      const label = input.closest('.field')?.querySelector('label');
      if (!label) return;
      let mark = label.querySelector('.required-mark');
      let optional = label.querySelector('.optional');
      if (!mark) {
        mark = document.createElement('span');
        mark.className = 'required-mark';
        mark.setAttribute('aria-hidden', 'true');
        mark.textContent = ' *';
        label.append(mark);
      }
      if (!optional) {
        optional = document.createElement('span');
        optional.className = 'optional';
        optional.textContent = ` (${form.dataset.optional})`;
        label.append(optional);
      }
      mark.hidden = !required;
      optional.hidden = required;
      for (const note of label.querySelectorAll('.visually-hidden')) note.hidden = !required;
    };
    const update = () => {
      const repository = kind.value === 'REPOSITORY';
      // Preserve entered values when switching types; hidden controls aren't sent.
      for (const [selector, hidden] of [['[data-deliverable-file]', repository], ['[data-deliverable-commit]', !repository]]) {
        const group = form.querySelector(selector);
        if (!group) continue;
        group.hidden = hidden;
        for (const field of group.querySelectorAll('input')) field.disabled = hidden;
      }
      setRequired('url', repository);
      setRequired('commit', repository);
    };
    kind.addEventListener('change', update);
    update();
  }
})();
