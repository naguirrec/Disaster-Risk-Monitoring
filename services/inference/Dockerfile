FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY segment.py cdse.py server.py model_card.json ./
COPY weights ./weights

# cdse.py guarda las escenas en $DRM_ROOT/data/copernicus; compose monta ahí un volumen.
ENV DRM_ROOT=/app
RUN mkdir -p /app/data/copernicus

EXPOSE 43124
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "43124"]
