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
# Timeweb App Platform performs the HTTP health check at /api/health,
# configured in application Settings > Deployment. A Dockerfile HEALTHCHECK
# would override the platform's setting, so this image intentionally omits it.
CMD ["sh", "./deploy/start.sh"]
