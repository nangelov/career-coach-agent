FROM python:3.12-slim

WORKDIR /app

# Install system packages as root
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget git curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Create logs directory as root
RUN mkdir -p /app/data

# Create a non-root user and set permissions
RUN useradd -m -u 1000 user && \
    chown -R user:user /app \
    && chown -R user:user /app/data

# Switch to non-root user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Copy Python requirements and install
COPY --chown=user requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy the entire project
COPY --chown=user . .

# Set up React frontend
WORKDIR /app/frontend

# Install dependencies and build
RUN npm install && npm run build

# Back to main app directory
WORKDIR /app

# Expose port (used by FastAPI)
EXPOSE 8000

CMD ["python", "main.py"]