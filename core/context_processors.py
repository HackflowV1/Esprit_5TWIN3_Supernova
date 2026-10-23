from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def interface(request):
    match = request.resolver_match
    app = match.app_name if match else ''
    page = match.url_name if match else ''
    account_titles = {
        'profile': _('Mon profil'), 'profile-edit': _('Modifier mon profil'),
        'password': _('Changer le mot de passe'), 'password-done': _('Mot de passe modifié'),
        'signup': _('Créer mon compte'), 'login': _('Connexion'),
        'skill-add': _('Ajouter une compétence'), 'skill-edit': _('Modifier une compétence'),
        'skill-delete': _('Retirer une compétence'),
    }
    event_titles = {
        'list': _('Les hackathons'), 'create': _('Créer un hackathon'),
        'dashboard': _('Control Tower'), 'compare': _('Comparer les éditions'),
        'edit': _('Configurer le hackathon'), 'manage': _('Pilotage'),
        'history': _('Historique'), 'roles': _('Gérer les rôles'),
        'organization-add': _('Créer une organisation'), 'propose': _('Proposer un challenge'),
        'track-add': _('Ajouter un track'), 'track-edit': _('Modifier un track'),
        'track-delete': _('Supprimer un track'), 'phase-add': _('Ajouter une phase'),
        'phase-edit': _('Modifier une phase'), 'phase-delete': _('Supprimer une phase'),
        'challenge-add': _('Ajouter un challenge'), 'challenge-edit': _('Modifier un challenge'),
        'challenge-delete': _('Supprimer un challenge'), 'sponsorship-add': _('Ajouter un partenariat'),
        'sponsorship-edit': _('Modifier un partenariat'), 'sponsorship-delete': _('Supprimer un partenariat'),
    }
    title = (account_titles if app == 'accounts' else event_titles).get(page, _('Configuration'))
    cancel_url = reverse('hackathons:list')
    if app == 'accounts':
        cancel_url = reverse('accounts:profile')
    elif match and match.kwargs.get('slug'):
        cancel_url = reverse('hackathons:detail' if page == 'propose' else 'hackathons:manage', kwargs={'slug': match.kwargs['slug']})
    return {'ui_app': app, 'ui_page': page, 'page_title': title, 'cancel_url': cancel_url}
