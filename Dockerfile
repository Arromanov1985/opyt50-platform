FROM python:3.13-slim
WORKDIR /srv
COPY requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt
COPY app ./app
COPY scripts ./scripts
RUN useradd -r -u 10001 opyt
USER opyt
EXPOSE 8000
CMD ["sh","-c","python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
