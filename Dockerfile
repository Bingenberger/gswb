FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
RUN groupadd --gid 10001 dictionary && useradd --uid 10001 --gid 10001 --no-create-home dictionary
COPY grundschul_woerterbuch ./grundschul_woerterbuch
COPY templates ./templates
COPY static ./static
COPY app.py ./
RUN mkdir -p /app/data/import_words /app/static/images /app/static/audio /app/static/uploads \
    && chown -R 10001:10001 /app/data /app/static/images /app/static/audio /app/static/uploads
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--worker-tmp-dir", "/tmp", "app:app"]
