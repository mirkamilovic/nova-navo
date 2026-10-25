FROM python:3.12-slim

COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY run.py .

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
CMD ["python", "run.py"]
