FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
# Несколько воркеров uvicorn: один процесс упирается в одно ядро, и любая
# тяжёлая синхронная операция (экспорт xlsx, разбор большого файла) задерживает
# остальные запросы. Число настраивается через API_WORKERS в .env.prod: 2 —
# безопасный компромисс для 4 ГБ ОЗУ (каждый воркер держит свой пул asyncpg).
ENV API_WORKERS=2
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-2}"]
