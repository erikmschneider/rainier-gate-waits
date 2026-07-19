FROM python:3.12-slim

WORKDIR /app
COPY . /app

ENV RAINIER_HOST=0.0.0.0 \
    RAINIER_PORT=8000 \
    RAINIER_DB_PATH=/data/rainier_waits.sqlite3

RUN mkdir -p /data

EXPOSE 8000
VOLUME ["/data"]

CMD ["python", "server.py"]
