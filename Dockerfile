FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY schema ./schema
COPY config ./config
COPY docs ./docs

RUN useradd --create-home --uid 1000 coursegen \
    && mkdir -p /app/artifacts \
    && chown -R coursegen:coursegen /app
USER coursegen

VOLUME ["/app/artifacts"]

ENTRYPOINT ["coursegen"]
CMD ["--help"]
