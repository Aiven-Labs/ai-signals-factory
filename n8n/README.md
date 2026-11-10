# n8n workflows

n8n is the visual DAG organisers use. The core app does the thinking; n8n schedules and carries messages.

- `daily-tick.json`: calls `POST /tick` every morning. UNTESTED export: import it and check.
- To build next: speaker-sheet poller (Google Sheets node, sheet to `/inbound`), approved-proposal executor
  (poll `GET /proposals?status=approved`, send via Gmail or post, then `POST /proposals/{id}/done`),
  Telegram and Slack triggers that call `/proposals/{id}/decide`.
- Unverified: how roles and per-person access work in n8n's free edition. Until checked, treat n8n
  accounts as admins only and keep organiser permissions in the core app.
