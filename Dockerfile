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
CMD ["sh", "./deploy/start.sh"]
