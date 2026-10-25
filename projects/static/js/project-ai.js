(() => {
  function initAIPanel() {
    const analyzeForm = document.getElementById('ai-analyze-form');
    const applyForm = document.getElementById('ai-apply-pitch-form');
    const statusBox = document.getElementById('ai-status');

    if (analyzeForm && !analyzeForm.dataset.bound) {
      analyzeForm.dataset.bound = 'true';
      analyzeForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = document.getElementById('ai-analyze-btn');
        if (!button || button.disabled) return;

        const originalText = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<span class="m3-spinner" aria-hidden="true"></span> Analyse en cours…';

        if (statusBox) {
          statusBox.hidden = false;
          statusBox.className = 'm3-ai-status is-loading';
          statusBox.textContent = 'Analyse de votre projet en cours… Cela peut prendre quelques secondes.';
        }

        try {
          const response = await fetch(analyzeForm.action, {
            method: 'POST',
            body: new FormData(analyzeForm),
            credentials: 'same-origin',
            headers: {
              'X-Requested-With': 'XMLHttpRequest',
              'Accept': 'application/json'
            }
          });
          const data = await response.json();
          if (response.ok && data.html) {
            const panel = document.getElementById('ai-assistant');
            if (panel) {
              panel.innerHTML = data.html;
              initAIPanel();
            }
          } else {
            const errorMsg = data.error || 'Une erreur est survenue lors de l’analyse. Veuillez réessayer.';
            if (statusBox) {
              statusBox.hidden = false;
              statusBox.className = 'm3-ai-status is-error';
              statusBox.textContent = errorMsg;
            }
            button.disabled = false;
            button.innerHTML = originalText;
          }
        } catch (err) {
          if (statusBox) {
            statusBox.hidden = false;
            statusBox.className = 'm3-ai-status is-error';
            statusBox.textContent = 'Connexion interrompue ou service indisponible. Veuillez réessayer.';
          }
          button.disabled = false;
          button.innerHTML = originalText;
        }
      });
    }

    if (applyForm && !applyForm.dataset.bound) {
      applyForm.dataset.bound = 'true';
      applyForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = document.getElementById('ai-apply-pitch-btn');
        if (!button || button.disabled) return;

        if (!confirm('Voulez-vous appliquer cette proposition de pitch à votre projet ? Votre pitch actuel sera mis à jour.')) {
          return;
        }

        const originalText = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<span class="m3-spinner" aria-hidden="true"></span> Application…';

        try {
          const response = await fetch(applyForm.action, {
            method: 'POST',
            body: new FormData(applyForm),
            credentials: 'same-origin',
            headers: {
              'X-Requested-With': 'XMLHttpRequest',
              'Accept': 'application/json'
            }
          });
          const data = await response.json();
          if (response.ok && data.success) {
            // Reload the page smoothly so all sections (pitch display, outdated badges, activities) reflect the update
            window.location.reload();
          } else {
            alert(data.error || 'Impossible d’appliquer le pitch.');
            button.disabled = false;
            button.innerHTML = originalText;
          }
        } catch (err) {
          alert('Une erreur réseau est survenue. Veuillez rafraîchir la page et réessayer.');
          button.disabled = false;
          button.innerHTML = originalText;
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAIPanel);
  } else {
    initAIPanel();
  }
})();
