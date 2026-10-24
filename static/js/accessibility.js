(function () {
  var api = window.HackFlowAccessibility;
  if (!api) return;
  var controls = Array.from(document.querySelectorAll('[data-a11y-setting]'));
  var dialog = document.getElementById('accessibility-dialog');
  var returnFocus;
  function sync() {
    var current = api.get();
    controls.forEach(function (control) {
      var value = current[control.dataset.a11ySetting];
      if (control.type === 'checkbox') control.checked = value;
      else control.value = value;
    });
  }
  function persist() {
    try {
      localStorage.setItem('hackflow-accessibility', JSON.stringify(api.get()));
      document.querySelectorAll('[data-a11y-storage-error]').forEach(function (message) { message.hidden = true; });
    }
    catch (_) {
      document.querySelectorAll('[data-a11y-storage-error]').forEach(function (message) { message.hidden = false; });
    }
  }
  controls.forEach(function (control) {
    control.addEventListener('change', function () {
      document.querySelectorAll('[data-a11y-reset-status]').forEach(function (status) { status.textContent = ''; });
      var current = api.get();
      current[control.dataset.a11ySetting] = control.type === 'checkbox' ? control.checked : control.value;
      api.apply(current);
      sync();
      persist();
    });
  });
  document.querySelectorAll('[data-a11y-reset]').forEach(function (button) {
    button.addEventListener('click', function () {
      api.apply(api.defaults); sync(); persist();
      document.querySelectorAll('[data-a11y-reset-status]').forEach(function (status) { status.textContent = button.dataset.resetMessage; });
    });
  });
  document.querySelectorAll('[data-a11y-open]').forEach(function (button) {
    button.addEventListener('click', function () {
      var menu = button.closest('details');
      returnFocus = menu ? menu.querySelector('summary') : button;
      if (menu) menu.open = false;
      if (dialog && !dialog.open) { sync(); dialog.showModal(); }
    });
  });
  if (dialog) {
    dialog.querySelector('[data-a11y-close]').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('close', function () { if (returnFocus && returnFocus.isConnected) returnFocus.focus(); });
  }
  window.addEventListener('storage', function (event) {
    if (event.key !== 'hackflow-accessibility' && event.key !== null) return;
    try { api.apply(event.newValue ? JSON.parse(event.newValue) : api.defaults); } catch (_) { api.apply(api.defaults); }
    sync();
  });
  sync();
})();
