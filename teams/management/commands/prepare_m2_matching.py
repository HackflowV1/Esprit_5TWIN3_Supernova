from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from teams import services
from teams.models import Team


class Command(BaseCommand):
    help = 'Explicitly download the small English M2 ONNX model, verify it and warm active team rankings.'

    def handle(self, **options):
        from teams.encoder import prepare,Encoder
        directory = Path(settings.M2_MODEL_CACHE)
        directory.mkdir(parents=True, exist_ok=True)
        self.stdout.write('Preparing small English MiniLM ONNX model (first download about 24 MB)...')
        prepare(directory)
        list(Encoder(directory).embed(['A solidarity project with mobile development.']))
        for team in Team.objects.filter(closed_at__isnull=True).select_related('hackathon', 'captain__user'):
            services.recommendations(actor=team.captain.user, team=team, background=False)
        self.stdout.write(self.style.SUCCESS('Model prepared; cached rankings available offline.'))
