FROM python:3.13-slim
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY deploy/start.sh ./deploy/start.sh
RUN useradd -r -u 10001 opyt && mkdir -p /srv/data && chown -R opyt /srv/data
USER opyt
ENV OPYT50_DB_PATH=/srv/data/opyt50.db
EXPOSE 8000
# Verify readiness inside the container. The public preview homepage is Basic Auth protected;
# /api/health is intentionally unauthenticated and returns HTTP 200.
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/api/health', timeout=3).close()" || exit 1
CMD ["sh", "./deploy/start.sh"]
