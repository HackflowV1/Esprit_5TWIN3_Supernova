'use strict';
document.getElementById('add-criterion')?.addEventListener('click', () => {
  const total = document.getElementById('id_form-TOTAL_FORMS');
  if (Number(total.value) >= 30) return;
  const fragment = document.getElementById('criterion-template').content.cloneNode(true);
  fragment.querySelectorAll('input, label').forEach(el => {
    for (const attr of ['name', 'id', 'for']) {
      if (el.hasAttribute(attr)) el.setAttribute(attr, el.getAttribute(attr).replaceAll('__prefix__', total.value));
    }
  });
  document.getElementById('criterion-rows').append(fragment);
  total.value = Number(total.value) + 1;
});
