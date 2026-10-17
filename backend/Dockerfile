FROM python:3.11-slim

# ffmpeg for librosa MP3 decode; libsndfile for soundfile/chord-extractor;
# build-essential for the vamp extension that chord-extractor compiles
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JS runtime for YouTube's challenges (yt-dlp-ejs)
COPY --from=denoland/deno:bin-2.1.4 /deno /usr/local/bin/deno

WORKDIR /app

# Image is CPU-only: install CPU torch first so demucs/torchaudio don't pull
# the multi-GB CUDA wheels. numpy + setuptools must be present before the
# vamp/chord-extractor build.
COPY requirements.txt install_deps.sh ./
RUN pip install --no-cache-dir -U pip wheel \
    && pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "numpy==1.26.4" "setuptools>=69,<81" \
    && pip install --no-cache-dir -r requirements.txt --no-build-isolation

COPY . .

ENV UPLOAD_DIR=/data/uploads
ENV CHORD_ENGINE=auto
RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
