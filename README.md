# AI Signals meetup factory

Runs the logistics of the AI Signals meetup with zero model calls by default.
Organisers approve every outward action from Telegram or Slack, and drive the workflows from n8n.

```
Forms (Sheets), email, Slack, GitHub board -> core app (Aiven Runtime) -> approval gate
                                             -> Postgres (Aiven) + Valkey
n8n (Aiven Runtime): schedules, sends approved actions, Telegram/Slack triggers
Nevia: small classifier model, S3 blob store for Langfuse, build agents (factory)
Langfuse (Aiven): traces and evals, with ClickHouse
```

## Layout
- `app/` core: `policy.py` roles, `schedule.py` event checklist, `classify.py` rules then optional small model, `main.py` API.
- `migrations/001_init.sql` schema. `templates/emails/` speaker emails.
- `n8n/`, `langfuse/`, `nevia/` deployment pieces. `.github/workflows/` CI and the label-triggered factory.

## Roles
admin, organiser, volunteer, observer (`app/policy.py`). Access grants need an admin and cannot be self-approved.

## Status
Tested: policy, schedule and classifier logic (`python -m pytest`).
Not yet run: the API against a real database, n8n workflows, Telegram/Slack wiring, the Nevia agent job (skeleton),
Langfuse deployment. Nothing here is deployed.
