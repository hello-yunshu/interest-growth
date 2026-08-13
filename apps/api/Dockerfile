FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "pydantic>=2.8" "sqlalchemy>=2.0" "httpx>=0.27" "PyYAML>=6.0" "websockets>=13" "python-multipart>=0.0.9"
COPY apps/api /app/apps/api
COPY packages /app/packages
COPY adapters /app/adapters
COPY plugins /app/plugins
COPY scripts /app/scripts
COPY domains /app/domains
COPY data /app/data
ENV PYTHONPATH=/app/apps/api:/app/packages/domain:/app/packages/plugin-runtime:/app/packages/engine-contracts:/app/packages/event-bus:/app/packages/artifacts:/app/packages/shared:/app/packages/native-execution-core:/app/adapters/deepseek
CMD ["uvicorn", "pg_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
