(function () {
  var nav = document.querySelector('[data-profile-nav]');
  if (!nav) return;
  var links = Array.from(nav.querySelectorAll('[data-profile-link]'));
  var panels = Array.from(document.querySelectorAll('[data-profile-panel]'));
  if (!panels.length) {
    var path = location.pathname;
    var current = path.includes('/skills/') ? 'skills' : path.includes('/password/') ? 'security' : 'information';
    links.find(function (link) { return link.dataset.profileLink === current; }).setAttribute('aria-current','page');
    return;
  }
  nav.setAttribute('role','tablist');
  var narrow = matchMedia('(max-width:760px)');
  function orientation() { nav.setAttribute('aria-orientation', narrow.matches ? 'horizontal' : 'vertical'); }
  orientation(); narrow.addEventListener('change',orientation);
  links.forEach(function (link) {
    var id = link.dataset.profileLink;
    link.id = 'profile-tab-' + id;
    link.setAttribute('role','tab'); link.setAttribute('aria-controls',id);
    var panel = document.getElementById(id);
    panel.setAttribute('role','tabpanel'); panel.setAttribute('aria-labelledby',link.id); panel.tabIndex = 0;
  });
  function activate(id, focus) {
    if (!links.some(function (link) { return link.dataset.profileLink === id; })) id = 'information';
    links.forEach(function (link) {
      var active = link.dataset.profileLink === id;
      link.setAttribute('aria-selected',String(active)); link.tabIndex = active ? 0 : -1;
      document.getElementById(link.dataset.profileLink).hidden = !active;
      if (active && focus) link.focus();
    });
  }
  links.forEach(function (link,index) {
    link.addEventListener('click',function (event) { event.preventDefault(); history.replaceState(null,'','#'+link.dataset.profileLink); activate(link.dataset.profileLink,false); });
    link.addEventListener('keydown',function (event) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      var next;
      if (['ArrowDown','ArrowRight'].includes(event.key)) next=(index+1)%links.length;
      if (['ArrowUp','ArrowLeft'].includes(event.key)) next=(index+links.length-1)%links.length;
      if (event.key==='Home') next=0;
      if (event.key==='End') next=links.length-1;
      if (next===undefined) return;
      event.preventDefault(); history.replaceState(null,'','#'+links[next].dataset.profileLink); activate(links[next].dataset.profileLink,true);
    });
  });
  window.addEventListener('hashchange',function () { activate(location.hash.slice(1),false); });
  activate(location.hash.slice(1),false);
})();
