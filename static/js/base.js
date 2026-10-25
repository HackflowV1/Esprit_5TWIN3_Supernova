/* HackFlow — base.js : améliorations progressives (menu mobile, mot de passe visible). */
(function () {
  document.documentElement.classList.add('js');

  /* Native disclosure menus keep a no-JavaScript fallback. */
  var menus = Array.from(document.querySelectorAll('[data-dropdown]'));
  menus.forEach(function (menu) {
    var summary = menu.querySelector('summary');
    summary.setAttribute('aria-expanded', String(menu.open));
    menu.addEventListener('toggle', function () {
      summary.setAttribute('aria-expanded', String(menu.open));
      if (menu.open) menus.forEach(function (other) { if (other !== menu) other.open = false; });
    });
  });
  document.addEventListener('click', function (event) {
    menus.forEach(function (menu) { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') menus.forEach(function (menu) {
      if (menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
    });
  });
  var themeSelects = Array.from(document.querySelectorAll('[data-theme-select]'));
  var themeSelect = themeSelects[0];
  document.querySelectorAll('[data-language-select]').forEach(function (select) {
    select.addEventListener('change', function () { select.form.requestSubmit(); });
  });
  var systemTheme = matchMedia('(prefers-color-scheme: dark)');
  function applyTheme(choice) {
    document.documentElement.dataset.themeChoice = choice;
    themeSelects.forEach(function (select) { select.value = choice; });
    document.documentElement.dataset.theme = choice === 'dark' || (choice === 'system' && systemTheme.matches) ? 'dark' : 'light';
  }
  themeSelects.forEach(function (select) {
    select.value = document.documentElement.dataset.themeChoice || 'system';
    select.addEventListener('change', function () {
      applyTheme(select.value);
      try { localStorage.setItem('hackflow-theme', select.value); } catch (_) {}
    });
  });
  systemTheme.addEventListener('change', function () {
    if (document.documentElement.dataset.themeChoice === 'system') applyTheme('system');
  });
  document.querySelectorAll('[data-dismiss-message]').forEach(function (button) {
    button.addEventListener('click', function () { button.closest('.message').remove(); });
  });
  var errorSummary = document.querySelector('[data-error-summary]');
  if (errorSummary) errorSummary.focus();

  var themeToggle = document.querySelector('[data-theme-toggle]');
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var current = document.documentElement.dataset.theme || 'light';
      var next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem('hackflow-theme', next); } catch (_) {}
      if (themeSelect) themeSelect.value = next;
    });
  }

  /* Content remains visible if scripts or observers are unavailable. */
  var landing = document.querySelector('.landing');
  if (landing && 'IntersectionObserver' in window && document.documentElement.dataset.a11yMotion !== 'reduce' && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('reveal-in');
          observer.unobserve(entry.target);
        }
      });
    }, {threshold: 0.08, rootMargin: '0px 0px -40px 0px'});
    landing.querySelectorAll('h1, h2, .hero-description, .hero-actions, .hero-perks, .hero-links, .hero-illustration, .event-card, .edition-empty, .role-intro, .role-card, .journey-illustration, .story-item, .faq-band, .landing-close').forEach(function (element) {
      element.classList.add('reveal-init');
      observer.observe(element);
    });
  }

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
  nav.addEventListener('click', function (event) {
    if (event.target.closest('a')) setOpen(false);
  });
  document.addEventListener('click', function (event) {
    if (!nav.contains(event.target) && event.target !== toggle) setOpen(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      setOpen(false);
      toggle.focus();
    }
  });
})();
