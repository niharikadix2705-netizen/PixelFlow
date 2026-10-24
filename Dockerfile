
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY worker.py .
COPY web ./web

RUN mkdir -p /app/processed_images

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
