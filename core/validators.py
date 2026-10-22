from django.core.exceptions import ValidationError


def validate_image_size(value):
    if value.size > 5 * 1024 * 1024:
        raise ValidationError('Image limitée à 5 Mo.')
