"""Private, atomic storage of the latest analysis without schema changes."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings

from .ai import AnalysisUnavailable


def _path(event, row):
    root = Path(getattr(settings, 'M5_AI_RESULTS_DIR', settings.BASE_DIR / 'evaluations' / '.ai_results'))
    return root / f'{int(event.pk)}-{int(row["submission_id"])}.json'


def load_analysis(event, row):
    try:
        data = json.loads(_path(event, row).read_text(encoding='utf-8'))
        if data.get('review_key') == row['review_key'] and isinstance(data.get('analysis'), str):
            return data['analysis']
    except (OSError, ValueError, AttributeError):
        pass
    return ''


def save_analysis(event, row, analysis):
    target = _path(event, row)
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({'review_key': row['review_key'], 'analysis': analysis}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError:
        raise AnalysisUnavailable('Impossible d’enregistrer la nouvelle analyse. L’ancienne est conservée.') from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
