FROM python:3.12-slim

RUN useradd -m -u 1000 user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Install system packages as root
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget git && \
    rm -rf /var/lib/apt/lists/*

# Switch to non-root user for the rest of the build
USER user

COPY --chown=user requirements.txt requirements.txt
RUN pip install --upgrade -r requirements.txt

COPY --chown=user . /app

# Expose Gradio port (used by Hugging Face Spaces)
EXPOSE 7860

CMD ["python", "main.py"]