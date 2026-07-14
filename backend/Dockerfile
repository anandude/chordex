FROM python:3.11-slim

# ffmpeg for librosa MP3 decode; libsndfile for soundfile/chord-extractor
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# numpy + setuptools must be present before vamp/chord-extractor build
COPY requirements.txt install_deps.sh ./
RUN pip install --no-cache-dir -U pip wheel \
    && pip install --no-cache-dir "numpy==1.26.4" "setuptools>=69,<81" \
    && pip install --no-cache-dir -r requirements.txt --no-build-isolation

COPY . .

ENV UPLOAD_DIR=/data/uploads
ENV CHORD_ENGINE=auto
RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
