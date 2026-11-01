# data/

Local data only. Everything in this folder except this file is git-ignored.

Suggested layout:

```
data/
├── raw/          downloaded job postings, public resume datasets (as received)
├── processed/    cleaned, de-duplicated, structured JSON/Parquet
└── labels/       your hand-labelled resume–job pairs (0–3 relevance)
```

Never put real people's resumes here. Use public datasets (e.g. on Kaggle) or synthetic resumes,
and check each source's licence before storing its data.
