FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system utilities needed for building/installing dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /code

# Copy requirements file first
COPY requirements.txt /code/requirements.txt

# Install Python requirements
RUN pip install --no-cache-dir -r /code/requirements.txt

# Run Playwright installation in the exact order requested
RUN pip install playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# Copy the rest of the application code
COPY . /code

# Expose the Hugging Face Space port
EXPOSE 7860

# Start FastAPI application using uvicorn on port 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
