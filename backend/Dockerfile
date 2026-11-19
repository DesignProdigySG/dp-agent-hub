FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY brand ./brand
RUN pip install --no-cache-dir -e '.[ollama,anthropic,openai]'
ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
