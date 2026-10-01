FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY segment.py server.py model_card.json ./
COPY weights ./weights

EXPOSE 43124
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "43124"]
