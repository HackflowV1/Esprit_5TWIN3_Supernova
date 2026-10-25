/* Fills the workshop form with the suggestion of the server. Values are set as plain text, never as HTML. */
(function () {
  var box = document.getElementById('ai-box');
  if (!box) return;
  var button = document.getElementById('ai-button');
  var status = document.getElementById('ai-status');
  var field = function (name) { return document.getElementById('id_' + name); };
  var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;

  function addMinutes(local, minutes) {
    var date = new Date(local);
    if (isNaN(date.getTime())) return '';
    date.setMinutes(date.getMinutes() + minutes - date.getTimezoneOffset());
    return date.toISOString().slice(0, 16);
  }

  button.addEventListener('click', function () {
    var hackathon = field('hackathon').value;
    if (!hackathon) { status.textContent = box.dataset.pick; field('hackathon').focus(); return; }
    button.disabled = true;
    status.textContent = box.dataset.busy;
    var body = new URLSearchParams({ hackathon: hackathon });
    fetch(box.dataset.url, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: body, credentials: 'same-origin' })
      .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
      .then(function (result) {
        if (!result.ok) { status.textContent = result.data.error || box.dataset.error; return; }
        var s = result.data;
        field('title').value = s.title;
        field('description').value = s.description;
        var start = field('start');
        if (start && start.value) field('end').value = addMinutes(start.value, s.duration_minutes);
        status.textContent = s.message;
        field('title').focus();
      })
      .catch(function () { status.textContent = box.dataset.error; })
      .finally(function () { button.disabled = false; });
  });
}());
