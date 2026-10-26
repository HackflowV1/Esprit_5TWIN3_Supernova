/* Retry only a read-only analysis while its local embedding is prepared.
   No script ever submits the confirmation form. Editing cancels the retry. */
(() => {
  const form = document.getElementById('m2-description-form');
  if (!form || form.dataset.autoRetry !== 'true') return;
  const timer = window.setTimeout(() => form.requestSubmit(), 1200);
  form.addEventListener('input', () => window.clearTimeout(timer), {once: true});
  form.addEventListener('submit', () => window.clearTimeout(timer), {once: true});
})();
