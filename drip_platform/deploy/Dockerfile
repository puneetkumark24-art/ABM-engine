# DRIP platform image — used by api, worker, and scheduler (same image, different command).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# system deps: libpq for psycopg2, curl for healthcheck, tini for signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl tini postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt deploy/requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-deploy.txt

COPY . .

# non-root runtime user
RUN useradd -m -u 10001 drip && chown -R drip:drip /app
USER drip

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
# default = API; worker/scheduler override `command:` in compose
CMD ["bash", "deploy/entrypoint_api.sh"]
