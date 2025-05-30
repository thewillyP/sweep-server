FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY entrypoint.sh .
COPY init_db.py .  
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]