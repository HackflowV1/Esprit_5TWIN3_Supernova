from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from teams import services
from teams.models import Team


class Command(BaseCommand):
    help = 'Explicitly download the local multilingual M2 model, verify it and warm active team rankings.'

    def handle(self, **options):
        from fastembed import TextEmbedding
        directory = Path(settings.M2_MODEL_CACHE)
        directory.mkdir(parents=True, exist_ok=True)
        self.stdout.write('Preparing local multilingual MiniLM model (first download about 220 MB)...')
        model = TextEmbedding(model_name=settings.M2_MODEL_NAME, cache_dir=str(directory), threads=2,
            providers=['CPUExecutionProvider'])
        list(model.embed(['Équipe solidaire, développement mobile.']))
        (directory / 'READY').write_text(settings.M2_MODEL_NAME, encoding='utf-8')
        for team in Team.objects.filter(closed_at__isnull=True).select_related('hackathon', 'captain__user'):
            services.recommendations(actor=team.captain.user, team=team, background=False)
        self.stdout.write(self.style.SUCCESS('Model prepared; cached rankings available offline.'))
