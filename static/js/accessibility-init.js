/* Apply device preferences before paint. Never trust values read from localStorage. */
(function () {
  var defaults = {colors:'standard', contrast:false, text:'normal', motion:'system', spacing:false, focus:false};
  function normalize(value) {
    value = value && typeof value === 'object' ? value : {};
    return {
      colors:['standard','red-green','blue-yellow','monochrome'].includes(value.colors) ? value.colors : defaults.colors,
      contrast:value.contrast === true,
      text:['normal','large','extra-large'].includes(value.text) ? value.text : defaults.text,
      motion:['system','reduce'].includes(value.motion) ? value.motion : defaults.motion,
      spacing:value.spacing === true,
      focus:value.focus === true
    };
  }
  var preferences = normalize(null);
  try { preferences = normalize(JSON.parse(localStorage.getItem('hackflow-accessibility'))); } catch (_) {}
  function apply(value) {
    preferences = normalize(value);
    Object.keys(preferences).forEach(function (key) {
      document.documentElement.setAttribute('data-a11y-' + key, String(preferences[key]));
    });
  }
  window.HackFlowAccessibility = {defaults:defaults, normalize:normalize, apply:apply, get:function () { return Object.assign({}, preferences); }};
  apply(preferences);
})();
