FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Apply migrations, then serve. Seeding/training are explicit one-off commands:
#   docker compose exec api python -m scripts.seed --reset
#   docker compose exec api python -m scripts.train_model --predict-all
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
