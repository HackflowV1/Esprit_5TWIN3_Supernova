/* HackFlow — base.js : améliorations progressives (menu mobile, mot de passe visible). */
(function () {
  document.documentElement.classList.add('js');

  /* Onglets accessibles (page de pilotage). Sans JavaScript, toutes les sections restent visibles. */
  var shell = document.querySelector('[data-tabs]');
  if (shell) {
    var tabs = [].slice.call(shell.querySelectorAll('[data-tab]'));
    var panels = tabs.map(function (tab) { return document.getElementById(tab.getAttribute('href').slice(1)); });
    var storeKey = 'hackflow-tab:' + location.pathname;
    shell.querySelector('[data-tablist]').setAttribute('role', 'tablist');

    tabs.forEach(function (tab, i) {
      var panelId = panels[i].id;
      tab.setAttribute('role', 'tab');
      tab.id = 'tab-' + panelId;
      tab.setAttribute('aria-controls', panelId);
      panels[i].setAttribute('role', 'tabpanel');
      panels[i].setAttribute('aria-labelledby', tab.id);
      panels[i].tabIndex = 0;
    });

    var activate = function (index, focus) {
      tabs.forEach(function (tab, j) {
        var on = index === j;
        tab.setAttribute('aria-selected', String(on));
        tab.tabIndex = on ? 0 : -1;
        panels[j].hidden = !on;
      });
      try { sessionStorage.setItem(storeKey, panels[index].id); } catch (e) { /* stockage indisponible */ }
      if (focus) { tabs[index].focus(); }
    };
    var indexFor = function (id) {
      return panels.findIndex(function (panel) { return panel.id === id; });
    };

    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function (event) {
        event.preventDefault();
        history.replaceState(null, '', '#' + panels[i].id);
        activate(i, false);
      });
      tab.addEventListener('keydown', function (event) {
        var next = null;
        if (event.key === 'ArrowDown' || event.key === 'ArrowRight') { next = (i + 1) % tabs.length; }
        if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') { next = (i - 1 + tabs.length) % tabs.length; }
        if (event.key === 'Home') { next = 0; }
        if (event.key === 'End') { next = tabs.length - 1; }
        if (next !== null) { event.preventDefault(); activate(next, true); }
      });
    });

    /* Liens internes vers un onglet (ex. « En chiffres »). */
    shell.querySelectorAll('.stat-links a').forEach(function (link) {
      link.addEventListener('click', function (event) {
        var target = indexFor(link.getAttribute('href').slice(1));
        if (target < 0) { return; }
        event.preventDefault();
        history.replaceState(null, '', link.getAttribute('href'));
        activate(target, true);
      });
    });

    var initial = indexFor(location.hash.slice(1));
    if (initial < 0) {
      try { initial = indexFor(sessionStorage.getItem(storeKey)); } catch (e) { initial = -1; }
    }
    shell.classList.add('tabs-ready');
    activate(initial < 0 ? 0 : initial, false);
    window.addEventListener('hashchange', function () {
      var target = indexFor(location.hash.slice(1));
      if (target >= 0) { activate(target, false); }
    });
  }

  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (!toggle || !nav) { return; }

  function setOpen(open) {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
  }

  toggle.addEventListener('click', function () {
    setOpen(toggle.getAttribute('aria-expanded') !== 'true');
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      setOpen(false);
      toggle.focus();
    }
  });
})();
