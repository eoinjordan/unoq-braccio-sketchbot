# Sketchbot for Arduino UNO Q (arm64 / aarch64).
# opencv-python-headless needs a few shared libs at runtime.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Gallery web server port.
EXPOSE 7100

# Default: run the live gallery. Override the command to run the pipeline, e.g.
#   docker compose run --rm sketchbot python -m sketch_artist.cli
CMD ["python", "-m", "web.server"]
