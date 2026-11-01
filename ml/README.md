# ml/

Experiments for the matching engine. Code that ships lives in `backend/app/services/`;
this folder is for evaluation and exploration.

## The evaluation plan

1. **Labelled set** — 100–150 resume–job pairs, each rated 0 (no fit) to 3 (strong fit).
   Store in `data/labels/pairs.csv` with columns: `resume_id, job_id, label`.
2. **Approaches to compare** (same pairs, same metric):

   | Approach | Idea |
   |---|---|
   | v0 hand-weighted formula | the original HireBot weights (skills 40, experience 30, education 15, keywords 15) |
   | TF-IDF keywords | classic information retrieval |
   | Embeddings | sentence-transformers cosine similarity |
   | Embeddings + LLM rerank | LLM re-orders the top candidates |
   | Trained ranker | LightGBM learning-to-rank on engineered features |

3. **Metrics** — NDCG@5 (ranking quality) and Spearman correlation with the labels.
4. **Fairness check** — confirm name, gender, photo and college are not features.

The admin console's *Model quality* page shows placeholder numbers until this table exists.

## Layout

```
ml/
├── notebooks/    exploration (01_eda.ipynb, 02_baselines.ipynb, …)
└── models/       trained artefacts (git-ignored)
```
