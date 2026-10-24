import hashlib
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


def validate_link(value):
    """Never fetch participant URLs; keep internal addresses and credentials out."""
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        if url.scheme != 'https' or not host or url.username or url.password or url.port not in (None, 443):
            raise ValueError
        if host == 'localhost' or '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError
    except ValueError:
        raise ValidationError(_('Utilisez un lien HTTPS public sans identifiants.')) from None


def validate_commit(value):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', value):
        raise ValidationError(_('Indiquez un hash Git complet de 40 ou 64 caractères.'))


def inspect_upload(upload):
    if upload.size > 20 * 1024 * 1024 or upload.size == 0:
        raise ValidationError(_('Le fichier doit peser entre 1 octet et 20 Mo.'))
    head = upload.read(16)
    upload.seek(0)
    extension = Path(upload.name).suffix.lower()
    valid = (extension == '.pdf' and head.startswith(b'%PDF-')) or (extension == '.zip' and head.startswith(b'PK\x03\x04')) or (extension == '.mp4' and head[4:8] == b'ftyp')
    if not valid:
        raise ValidationError(_('Formats autorisés : PDF, ZIP et MP4, avec un contenu correspondant.'))
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return {'size': upload.size, 'sha256': digest.hexdigest(), 'original_name': Path(upload.name).name}
