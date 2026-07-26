FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -e ".[dev]"

# data/ holds real pipeline state (data/manifest.db, data/raw/, data/chunks/,
# data/extracted/) that must persist across separate `docker run` invocations
# for each stage -- always mount a host directory here (-v .../data:/app/data),
# never rely on whatever the image happens to contain.
VOLUME ["/app/data"]

CMD ["python", "-c", "print('course-dataset-pipeline image ready -- run a stage explicitly, e.g.: python -m src.retrieve.batch')"]
