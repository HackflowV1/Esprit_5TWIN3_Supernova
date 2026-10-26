import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from teams import evaluation, matching


class Command(BaseCommand):
    help = 'Compare keyword/rules/hybrid ranking on held-out cases. Human CSV labels required for quality metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--export', help='Create a NEW blank human review CSV; never overwrite existing judgments.')
        parser.add_argument('--labels', help='Completed human-reviewed CSV, with 0/1/2 relevance and reviewer name.')
        parser.add_argument('--output', help='Optional JSON report file.')

    def handle(self, **options):
        if options['export']:
            try:
                evaluation.export_sheet(options['export'])
            except FileExistsError as exc:
                raise CommandError('Review file already exists; refusing to overwrite it.') from exc
            self.stdout.write('Blank review sheet exported; no quality measurements claimed.')
            return
        try:
            labels = evaluation.read_labels(options['labels']) if options['labels'] else None
        except (ValueError, KeyError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        report = {'version':matching.VERSION,'model':settings.M2_MODEL_NAME,
            'quality_status':'human_reviewed' if labels else 'awaiting_human_review',
            'dataset':'held-out fictional cases; separate from seed; not a real-world validation',
            'precision_definition':'relevance >= 1; grade 2 means strong match',
            'modes':{}}
        for mode in ('keywords','rules','hybrid'):
            rows, timings = [], []
            for case in evaluation.CASES:
                team,needs,candidates = evaluation.inputs(case)
                # Explicit CLI may compute cache misses; HTTP never does.
                start = perf_counter()
                ranking = matching.rank(team=team,needs=needs,candidates=candidates,mode=mode,background=False)
                cold_ms = (perf_counter()-start)*1000
                for _ in range(5):
                    start = perf_counter()
                    matching.rank(team=team,needs=needs,candidates=candidates,mode=mode,background=False)
                    timings.append((perf_counter()-start)*1000)
                ids = [r['registration'].pk for r in ranking]
                row = {'case':case[0],'top_3':ids[:3],'model_state':ranking[0]['matching_state'],'first_call_ms':round(cold_ms,2)}
                if labels:
                    row.update(evaluation.metrics(ids,{p[0]:labels[(case[0],p[0])] for p in evaluation.PEOPLE}))
                rows.append(row)
            result = {'cases':rows,'warm_mean_ms':round(mean(timings),2),'warm_p95_ms':round(sorted(timings)[int(.95*(len(timings)-1))],2)}
            if labels:
                result['mean_precision_at_3'] = mean(r['precision_at_3'] for r in rows)
                result['mean_ndcg_at_3'] = mean(r['ndcg_at_3'] for r in rows)
            report['modes'][mode] = result
        report['hybrid_available'] = all(r['model_state'] == 'ready' for r in report['modes']['hybrid']['cases'])
        if not report['hybrid_available']:
            report['hybrid_note'] = 'Hybrid fell back to rules. Prepare the model before comparing AI quality.'
        text = json.dumps(report,ensure_ascii=False,indent=2)
        if options['output']:
            Path(options['output']).write_text(text,encoding='utf-8')
        self.stdout.write(text)
