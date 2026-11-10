# Langfuse

Use Aiven's Runtime template as the base: https://github.com/Aiven-Labs/aiven-runtime-langfuse (not yet read).

Wiring:
- Postgres: database `langfuse` on `factory-pg`.
- Valkey: `factory-valkey`.
- ClickHouse: create `startup-8` only when deploying (about $212/month running 24/7).
- Blob: S3 endpoint on the Nevia `blob` computer, bucket `langfuse` (see `nevia/blob-setup.sh`).
- Trace every model call from `app/classify.py`, and log it to `llm_calls`.
