# Team skill-needs suggestion data

Three JSONL splits for suggesting which existing team-skill labels may be relevant to a short project description. Rows are synthetic and authored for this task; they are not extracted from users, projects, or production data. `source` is `gpt-6-luna-synthetic`; every row is marked `unreviewed`.

## Annotation

Labels are limited to the app's existing names: API REST, Cybersécurité, Data Science, DevOps, Django, Figma, JavaScript, Machine Learning, Mobile, PostgreSQL, Python, React, and UI/UX. A label means the description supports suggesting that capability, not that a team must have it or that a person is certified. Empty `labels` means the text does not support a specific listed skill. Broad ideas and irrelevant descriptions are intentionally included.

Only explicit or clear paraphrased capability needs are labeled. Django does not imply Python; generic frontend work does not imply React or JavaScript; SQL without PostgreSQL does not imply PostgreSQL; Machine Learning does not imply Python or Data Science. Excluded, optional, or alternative technologies are not required labels. Figma is labeled only when named. UI/UX needs may be described as usability, accessibility, interaction, or interface design.

`group` identifies a scenario family. Any related text variants stay together in one split. Validation and test use different scenario families from training. The test split is a synthetic held-out set, not independently reviewed evaluation data. No real-world accuracy claim is supported by these files. Review and correct the annotations before using them for model training or evaluation.

## Split counts

| Split | Rows | Empty labels | French | English |
|---|---:|---:|---:|---:|
| train | 80 | 8 (10.0%) | 38 | 42 |
| validation | 26 | 2 (7.7%) | 12 | 14 |
| test | 39 | 5 (12.8%) | 18 | 21 |
| train_extra | 60 | 10 (16.7%) | 30 | 30 |
| validation_extra | 20 | 4 (20.0%) | 10 | 10 |
| final_test | 39 | 5 (12.8%) | 17 | 22 |

All 13 labels appear in every file. The supplemental training set has 34 multi-label rows, 16 single-label rows, and 10 empty-label rows. The supplemental validation set has 11 multi-label rows, 5 single-label rows, and 4 empty-label rows. `final_test.jsonl` contains fresh scenario groups distinct from every other file; it has 4 multi-label rows, 30 single-label rows, and 5 empty-label rows. The test files are synthetic held-out data, not independently reviewed evaluation data, and do not support a real-world accuracy claim. Keep `final_test.jsonl` separate from training and threshold selection; review annotations before making evaluation claims.

The base train and validation files received an **AI annotation audit, not human review**. The supplemental files were also checked by AI for label support and schema consistency; no human review has taken place. `review_status` remains `unreviewed` on every row.

Each row has `id`, `text`, `labels`, `language`, `group`, `source`, and `review_status`.
