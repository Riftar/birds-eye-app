FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY birds_eye ./birds_eye
COPY mock-data ./mock-data
RUN pip install --no-cache-dir .
ENV PORT=8000
CMD ["sh", "-c", "exec uvicorn birds_eye.app:create_app --factory --host 0.0.0.0 --port ${PORT} --workers 1"]
