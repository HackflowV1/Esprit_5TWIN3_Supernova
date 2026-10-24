"""Shared UI helpers; business permissions stay in services."""
from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_noop

register = template.Library()
ICONS = frozenset('add edit delete view search arrow-right arrow-left chevron-down chevron-right home calendar users user logout settings globe sun moon monitor check close menu code dashboard clock archive help shield link filter compare history upload save building award accessibility'.split())
# History keeps stable source labels in the database; translate only their display.
HISTORY_LABELS = (
    gettext_noop('Création'), gettext_noop('Modification'), gettext_noop('Configuration'),
    gettext_noop('Statut'), gettext_noop('Suppression'), gettext_noop('Affectation de rôle'),
    gettext_noop('Organisation créée'), gettext_noop('Proposition sponsor'),
    gettext_noop('Challenge : validation'), gettext_noop('Challenge : publication'),
    gettext_noop('Challenge : retrait'),
)


@register.simple_tag
def icon(name, size=18):
    if name not in ICONS:
        return ''
    return format_html('<svg class="icon" width="{}" height="{}" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><use href="{}#{}"></use></svg>', size, size, static('icons/hugeicons.svg') + '?v=2', name)


@register.filter(name='translate')
def translate_label(value):
    """Only application labels, never user-authored content."""
    return gettext(str(value)) if value else value


@register.inclusion_tag('shared/field.html')
def render_field(field):
    descriptions = []
    if field.help_text:
        descriptions.append(f'{field.auto_id}_helptext')
    if field.errors:
        descriptions.append(f'{field.auto_id}_error')
    attrs = {'aria-describedby': ' '.join(descriptions)} if descriptions else {}
    if field.errors:
        attrs['aria-invalid'] = 'true'
    return {'field': field, 'widget': field.as_widget(attrs=attrs)}
