"""Held-out fictional evaluation inputs. Grades must come from human reviewers.

These examples are independent of the demo seed; they are not training data.
"""
import csv
import math
from types import SimpleNamespace as NS

CASES = [
    ('mobility', 'Aider les cyclistes à repérer les stationnements vélos accessibles et sûrs.', [('Mobile',3,3), ('UI/UX',2,1)]),
    ('libraries', 'A multilingual library catalog and accessible search for university students.', [('Django',3,3), ('UI/UX',3,2)]),
    ('energy', 'Prévoir la consommation énergétique de bâtiments à partir de séries temporelles explicables.', [('Machine Learning',3,3), ('Python',3,2)]),
    ('privacy', 'An open source toolkit to protect personal data in student web apps.', [('Cybersécurité',3,3), ('Django',2,2)]),
]
PEOPLE = [
    ('eval-a', {'Mobile':4,'UI/UX':3}, 'I build accessible route-planning apps for cyclists and public transport users.'),
    ('eval-b', {'Mobile':4,'UI/UX':3}, 'Développement de jeux mobiles et expériences musicales.'),
    ('eval-c', {'Django':4,'UI/UX':3}, 'Catalogues documentaires multilingues, recherche et accessibilité des bibliothèques.'),
    ('eval-d', {'Django':4,'UI/UX':3}, 'Online ticket sales, shopping carts and payment interfaces.'),
    ('eval-e', {'Machine Learning':4,'Python':4}, 'Time-series forecasting for building energy use and interpretable models.'),
    ('eval-f', {'Python':2,'Machine Learning':2}, 'Je découvre les prévisions de consommation énergétique.'),
    ('eval-g', {'Cybersécurité':4,'Django':3}, 'Audit des applications web et protection des données personnelles des étudiants.'),
    ('eval-h', {}, 'Mobile UI/UX Django Machine Learning Python Cybersécurité. Je cherche ma première expérience et apprends ces sujets.'),
]


class Rows(list):
    def all(self):
        return self


def inputs(case):
    case_id, description, declarations = case
    names = sorted({s for _, skills, _ in PEOPLE for s in skills} | {s for s,_,_ in declarations})
    ids = {name:i for i,name in enumerate(names)}
    needs = [NS(skill=NS(name=name),skill_id=ids[name],level=level,priority=priority,covered_by=[]) for name,level,priority in declarations]
    regs = [NS(pk=name,user=NS(username=name,profile=NS(biography=bio,interests=''),user_skills=Rows([
        NS(skill=NS(name=skill),skill_id=ids[skill],level=level,experience='') for skill,level in skills.items()])))
        for name,skills,bio in PEOPLE]
    return NS(description=description), needs, regs


def export_sheet(path):
    with open(path, 'x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['case_id','candidate_id','team_idea','missing_needs','declared_skills','biography','relevance','reviewer','notes'])
        for case_id, description, needs in CASES:
            for candidate, skills, bio in PEOPLE:
                writer.writerow([case_id,candidate,description,str(needs),str(skills),bio,'','',''])


def read_labels(path):
    expected = {(case[0],person[0]) for case in CASES for person in PEOPLE}
    labels = {}
    with open(path, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            key = (row['case_id'],row['candidate_id'])
            if key not in expected or key in labels:
                raise ValueError('Unknown or duplicate case/candidate pair.')
            if row['relevance'] not in ('0','1','2') or not row['reviewer'].strip():
                raise ValueError('Every pair needs a human grade (0/1/2) and reviewer name. Blank templates are not results.')
            labels[key] = int(row['relevance'])
    if set(labels) != expected:
        raise ValueError('Complete every pair before computing comparable metrics.')
    return labels


def metrics(ranking, grades, k=3):
    selected = ranking[:k]
    precision = sum(grades[x] >= 1 for x in selected) / k
    dcg = sum((2**grades[x]-1)/math.log2(i+2) for i,x in enumerate(selected))
    ideal = sum((2**g-1)/math.log2(i+2) for i,g in enumerate(sorted(grades.values(),reverse=True)[:k]))
    return {'precision_at_3':precision,'ndcg_at_3':dcg/ideal if ideal else 0}
