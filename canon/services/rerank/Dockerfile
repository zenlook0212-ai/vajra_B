FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn sentence-transformers
COPY app.py /app/app.py
EXPOSE 8007
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8007"]
