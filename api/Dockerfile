# FB12 Dutch API. Build context: the api/ folder.
# Stage "test" runs the suite; stage "runtime" copies a marker from it, so a
# failing test fails the build and nothing deploys.

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS test
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
RUN python -m pytest -q && echo "tests passed" > /tests-passed

FROM base AS runtime
COPY main.py ./
COPY config ./config
COPY core ./core
COPY models ./models
COPY routers ./routers
COPY services ./services
COPY --from=test /tests-passed /tests-passed
RUN useradd --create-home --uid 10001 fb12 && chown -R fb12:fb12 /app
USER fb12
EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
