FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini pytest.ini ./
# Tests ship in the image so `make test` runs the same code that deploys,
# rather than whatever happens to be mounted from the host.
COPY tests ./tests
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

# entrypoint.sh runs `alembic upgrade head`, then uvicorn with one worker.
# One worker on purpose: app/core/rate_limit.py counts login failures in process
# memory, so a second worker makes the R-2.4 login throttle bypassable.
# See docs/SERVER-INFRASTRUCTURE.md before changing either.
CMD ["./entrypoint.sh"]
