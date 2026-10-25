'use strict';
const form = document.getElementById('evaluation-form');
const updateTotal = () => {
  let total = 0, complete = true;
  const inputs = form.querySelectorAll('[data-weight]');
  inputs.forEach(input => {
    const value = Number(input.value), max = Number(input.dataset.maximum);
    if (input.value === '' || !Number.isFinite(value) || value < 0 || value > max) complete = false;
    total += value / max * Number(input.dataset.weight);
  });
  document.getElementById('total-score').textContent = complete && inputs.length ? total.toFixed(2) : '—';
};
form?.addEventListener('input', updateTotal);
if (form) updateTotal();
