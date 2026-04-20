FROM python:3.11-slim

WORKDIR /app

# تثبيت المتطلبات النظامية (cairo للـ PDF، fonts للعربية)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

# تثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir --timeout 900 --retries 10 emergentintegrations==0.1.0 \
      --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/

# نسخ الكود
COPY . .

RUN pip install --no-cache-dir --timeout 900 --retries 10 emergentintegrations==0.1.0 \
# إنشاء مجلدات الرفع
RUN mkdir -p uploads reg_uploads

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
