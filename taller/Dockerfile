FROM python:3.11-slim

# Evitar buffers y escribir bytecode innecesario
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Instalar dependencias del sistema mínimas para compilar y ejecutar reportlab / postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar librerías de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . .

# Permisos de ejecución al entrypoint
RUN chmod +x entrypoint.sh

# Exponer el puerto de Flask/Gunicorn
EXPOSE 5000

# Punto de entrada
ENTRYPOINT ["/app/entrypoint.sh"]
