FROM python:3.12-slim

WORKDIR /srv
COPY config /srv/config
COPY apps/api /srv/apps/api
WORKDIR /srv/apps/api
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/srv/apps/api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
