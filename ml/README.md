# ml/

Experiments for the matching engine. Code that ships lives in `backend/app/services/`;
this folder is for evaluation and exploration.

## Where the matcher is today

`backend/app/services/matching.py` (version `rules-2`) scores a candidate against a job with five weighted parts.
The defaults are skills 40, qualification 20, experience 30, location 5 and keywords 5; a recruiter can change them per run.
A part that cannot be judged from the data (for example, a job with no stated degree) is left out and the rest are re-weighted,
so it never counts as a silent zero. Qualification compares degree level only, and the institution is never read.
An AI second look can lift a missing skill to half credit, but only with a quote that is found in the resume.

This is the baseline the other approaches are compared with. Recruiters' thumbs up and down on matches are stored
(`match_feedback`) as labels for the trained ranker, and never change a score today.

## The evaluation plan

1. **Labelled set** - 100-150 resume-job pairs, each rated 0 (no fit) to 3 (strong fit).
   Store in `data/labels/pairs.csv` with columns: `resume_id, job_id, label`.
2. **Approaches to compare** (same pairs, same metric):

   | Approach | Idea |
   |---|---|
   | v0 hand-weighted formula | the original HireBot weights (skills 40, experience 30, education 15, keywords 15) |
   | rules-2 (shipped) | the five-part matcher above |
   | TF-IDF keywords | classic information retrieval |
   | Embeddings | sentence-transformers cosine similarity |
   | Embeddings + LLM rerank | LLM re-orders the top candidates |
   | Trained ranker | LightGBM learning-to-rank on engineered features, trained on the labelled set and recruiter thumbs |

3. **Metrics** - NDCG@5 (ranking quality) and Spearman correlation with the labels.
4. **Fairness check** - confirm name, gender, photo and college are not features.

The admin console's *Model quality* page stays empty until this table exists. It will not show placeholder numbers.

## Layout

```
ml/
├── notebooks/    exploration (01_eda.ipynb, 02_baselines.ipynb, ...)
└── models/       trained artefacts (git-ignored)
```
