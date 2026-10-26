# Build from the repo root:  docker build -f app/Dockerfile -t fantasyfb-web .
# Only the paths whitelisted in /.dockerignore are copied in.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as an unprivileged user (some hosts, such as Hugging Face Spaces, require uid 1000).
RUN useradd -m -u 1000 user
WORKDIR /home/user/fantasyfb

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY app ./app
# Constraints pin every dependency to the versions the tests ran on (see the file's header).
RUN pip install . -r app/requirements.txt -c app/constraints.txt

# WORKDIR is created as root, but a run writes NewInjuries.csv/OldInjuries.csv
# to the working directory, so the unprivileged user needs to own it.
RUN chown user:user /home/user/fantasyfb

USER user
ENV HOME=/home/user \
    NFLREADPY_CACHE_DIR=/home/user/.cache/nflreadpy \
    PORT=7860
EXPOSE 7860

# --proxy-headers: behind a host's proxy, so request.client is the visitor's
# address (used for the one-run-per-visitor limit) rather than the proxy's.
CMD ["sh", "-c", "exec uvicorn fantasyfb_web.main:app --app-dir app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
