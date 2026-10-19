# Dockerfile for a Hugging Face Space. The Space is its own git repo containing
# only this file and README.md; it builds the app by cloning fantasyfb from GitHub.
# Pin FANTASYFB_REF to a release tag or commit to control when the Space updates.
FROM python:3.12-slim

ARG FANTASYFB_REF=main

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
WORKDIR /home/user

RUN git clone --depth 1 --branch "${FANTASYFB_REF}" https://github.com/tefirman/fantasyfb.git fantasyfb \
    && cd fantasyfb \
    && pip install . -r app/requirements.txt \
    && chown -R user:user /home/user

USER user
WORKDIR /home/user/fantasyfb
ENV HOME=/home/user \
    NFLREADPY_CACHE_DIR=/home/user/.cache/nflreadpy \
    PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "exec uvicorn fantasyfb_web.main:app --app-dir app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
