FROM python:3.10-slim

WORKDIR /app

# Sistem bağımlılıklarını güncelle (Slim imajlarda gerekebilir)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Önce pip'i güncelle, sonra requests'i manuel olarak ekleyerek yükle
RUN pip install --upgrade pip
RUN pip install --no-cache-dir requests  
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]