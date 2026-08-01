# One image, three roles: api, worker, and beat all run this exact image
# with a different `command:` in docker-compose.yml (uvicorn / celery
# worker / celery beat). The image is the environment; the command picked
# at run time is the role. See docs/infra-guide.md.
FROM python:3.13-slim

# Python block-buffers stdout by default whenever it isn't a TTY, which is
# always true inside a container. uvicorn's own access-log volume masks
# this for the api service, but the Celery worker's prefork children sit
# idle between tasks and can leave a single structlog JSON line (e.g. a
# task_failed entry) stuck in an unflushed buffer indefinitely -- observed
# for real during the v0.5 slice 2 production drill: a task that failed
# with a clear traceback in Celery's own result backend produced zero
# corresponding output in `docker logs` or CloudWatch, for over 7 minutes.
# See docs/decisions.md.
ENV PYTHONUNBUFFERED=1

# psycopg2-binary and pandas both ship prebuilt wheels for this base image,
# so no compiler toolchain is needed here -- keep it that way; adding
# build-essential "to fix a wheel" is usually a sign the wrong wheel/arch
# was pulled, not that a compiler is actually required.
WORKDIR /app

# Copy dependency files and install before the rest of the app code, so
# editing application code doesn't invalidate this layer's build cache --
# `docker build` re-runs everything after the first changed layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user -- if a dependency (or a future eval'd LLM output)
# is ever compromised, this limits what it can do to the container.
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# No CMD here on purpose -- docker-compose.yml (and docker-compose.prod.yml)
# supplies the actual command per service (uvicorn/worker/beat), which is
# the "one image, three roles" pattern above.
