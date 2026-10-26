# English team skill-needs dataset

English-only companion data for the team-skill suggestion pilot. These files combine the existing bilingual training and validation data with English translations of French text. The separate held-out file contains the previously authored final-test scenarios. No new scenarios or labels were introduced in this conversion.

## Files and counts

| File | Rows | Empty-label rows | Translated by GPT-6 Luna | Original English |
|---|---:|---:|---:|---:|
| `train.jsonl` | 140 | 18 | 68 | 72 |
| `validation.jsonl` | 46 | 6 | 22 | 24 |
| `final_test.jsonl` | 39 | 5 | 17 | 22 |

Each row preserves its original ID, labels, scenario group, source, and review status. The `language` field is `en`. The added `translation` field is `gpt-6-luna` for translated French text and `original-en` for text already written in English.

## Provenance and limitations

All examples are synthetic. French text was translated into English by GPT-6 Luna; English rows were copied from the source data. Translations are machine-generated, labels remain unreviewed, and `review_status` is still `unreviewed`. This dataset has not received independent human annotation or review and cannot support claims about real-world model accuracy. Keep `final_test.jsonl` separate from training, model selection, and threshold tuning.

The app's exact labels remain: API REST, Cybersécurité, Data Science, DevOps, Django, Figma, JavaScript, Machine Learning, Mobile, PostgreSQL, Python, React, and UI/UX. Annotation rules and known limitations are described in the bilingual dataset's README.
