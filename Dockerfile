FROM python:3.11-slim

WORKDIR /app

# Install system dependencies: curl + Playwright/Chromium requirements
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser and system deps for Playwright
RUN playwright install --with-deps chromium

COPY . .

ENV PLAYWRIGHT_ENABLED=1

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
