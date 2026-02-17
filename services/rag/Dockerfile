FROM python:3.11-slim

WORKDIR /app

# docling может требовать системные библиотеки для PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH=/app

EXPOSE 8020
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
