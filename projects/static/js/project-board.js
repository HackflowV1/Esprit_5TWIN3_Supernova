/* Native drag-and-drop, with ordinary POST buttons for keyboard/touch/no-JS use.
 * The server returns authoritative board markup; failed saves never move a card.
 */
(() => {
  let busy = false;
  function bindBoard(board) {
    if (!board || board.dataset.movable !== 'true') return;
    let dragged = null;
    const clearDrag = () => {
      board.querySelectorAll('.is-dragging,.is-drop-target').forEach(element => {
        element.classList.remove('is-dragging', 'is-drop-target');
      });
    };
    for (const card of board.querySelectorAll('[data-move-url]')) {
      card.draggable = true;
      for (const link of card.querySelectorAll('a')) link.draggable = false;
    }
    async function move(card, state, keyboard = false) {
      if (busy || !card || card.closest('.m3-column')?.dataset.state === state) return;
      const csrf = board.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
      if (!csrf) return;
      const status = board.querySelector('[data-board-status]');
      const milestoneId = card.dataset.milestone;
      busy = true;
      clearDrag();
      board.setAttribute('aria-busy', 'true');
      board.classList.add('is-saving');
      if (status) {
        status.textContent = board.dataset.saving;
        status.removeAttribute('data-error');
      }
      try {
        const response = await fetch(card.dataset.moveUrl, {
          method: 'POST', credentials: 'same-origin',
          headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
          body: new URLSearchParams({state})
        });
        const data = await response.json();
        if (!response.ok || typeof data.board_html !== 'string') throw new Error(data.error || board.dataset.saveError);
        const fragment = document.createElement('template');
        fragment.innerHTML = data.board_html;
        const updated = fragment.content.querySelector('#board');
        if (!updated) throw new Error(board.dataset.saveError);
        const scrollLeft = board.querySelector('.m3-kanban')?.scrollLeft || 0;
        board.replaceWith(updated);
        const scroller = updated.querySelector('.m3-kanban');
        if (scroller) scroller.scrollLeft = scrollLeft;
        bindBoard(updated);
        if (typeof data.activity_html === 'string') {
          const activity = document.createElement('template');
          activity.innerHTML = data.activity_html;
          const nextActivity = activity.content.querySelector('#activity');
          if (nextActivity) document.getElementById('activity')?.replaceWith(nextActivity);
        }
        if (keyboard) {
          const movedCard = updated.querySelector(`[data-milestone="${milestoneId}"]`);
          movedCard?.querySelector('.m3-card-menu summary')?.focus({preventScroll: true});
          movedCard?.scrollIntoView({block: 'nearest', inline: 'nearest'});
        }
        requestAnimationFrame(() => {
          const message = updated.querySelector('[data-board-status]');
          if (message) message.textContent = data.message;
        });
      } catch (error) {
        if (status) {
          status.textContent = error instanceof SyntaxError || error instanceof TypeError ? board.dataset.saveError : error.message;
          status.dataset.error = 'true';
        }
      } finally {
        busy = false;
        board.removeAttribute('aria-busy');
        board.classList.remove('is-saving');
      }
    }
    board.addEventListener('dragstart', event => {
      const card = event.target.closest('[data-move-url]');
      if (!card || busy || event.target.closest('summary,button,input,select,form')) {
        event.preventDefault();
        return;
      }
      dragged = card;
      board.querySelectorAll('.m3-card-menu[open]').forEach(menu => menu.removeAttribute('open'));
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', card.dataset.milestone);
      card.classList.add('is-dragging');
    });
    board.addEventListener('dragover', event => {
      const column = event.target.closest('.m3-column');
      if (!dragged || busy || !column || !board.contains(column)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      board.querySelectorAll('.is-drop-target').forEach(item => item.classList.remove('is-drop-target'));
      if (column !== dragged.closest('.m3-column')) column.classList.add('is-drop-target');
    });
    board.addEventListener('dragleave', event => {
      const column = event.target.closest('.m3-column');
      if (column && !column.contains(event.relatedTarget)) column.classList.remove('is-drop-target');
    });
    board.addEventListener('drop', event => {
      const column = event.target.closest('.m3-column');
      if (!dragged || !column || !board.contains(column)) return;
      event.preventDefault();
      const card = dragged;
      dragged = null;
      clearDrag();
      void move(card, column.dataset.state);
    });
    board.addEventListener('dragend', () => {dragged = null; clearDrag();});
    board.addEventListener('submit', event => {
      const form = event.target.closest('[data-milestone-move]');
      if (!form) return;
      event.preventDefault();
      const state = event.submitter?.value || form.querySelector('[name="state"]')?.value;
      if (state) void move(form.closest('[data-move-url]'), state, true);
    });
  }
  bindBoard(document.getElementById('board'));
})();
