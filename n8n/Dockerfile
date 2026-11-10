FROM docker.n8n.io/n8nio/n8n:2.48.0
# Aiven injects one connection URI (N8N_DB_URL); n8n wants split DB_POSTGRESDB_* vars.
# entrypoint.sh splits it and trusts the Aiven project CA, then starts n8n.
COPY entrypoint.sh /entrypoint.sh
ENV DB_TYPE=postgresdb N8N_PORT=5678 N8N_PROTOCOL=https N8N_PROXY_HOPS=1 \
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false GENERIC_TIMEZONE=Europe/London
EXPOSE 5678
ENTRYPOINT ["tini", "--", "/entrypoint.sh"]
