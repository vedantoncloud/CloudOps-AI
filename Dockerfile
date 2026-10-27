FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLOUDOPS_ENV=production \
    CLOUDOPS_AUTH_MODE=token \
    CLOUDOPS_AUDIT_EVENTS_DB=/var/lib/cloudops/audit-events.db \
    CLOUDOPS_AUDIT_IDEMPOTENCY_DB=/var/lib/cloudops/audit-idempotency.db \
    CLOUDOPS_ACTION_PLANS_DB_PATH=/var/lib/cloudops/action-plans.db \
    CLOUDOPS_GITOPS_DB_PATH=/var/lib/cloudops/gitops.db

WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /app/requirements.txt \
    && groupadd --system cloudops \
    && useradd --system --gid cloudops --home-dir /nonexistent --shell /usr/sbin/nologin cloudops \
    && mkdir -p /var/lib/cloudops \
    && chown cloudops:cloudops /var/lib/cloudops

COPY --chown=cloudops:cloudops backend/ /app/backend/
WORKDIR /app/backend
USER cloudops
VOLUME ["/var/lib/cloudops"]
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
