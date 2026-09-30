FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY config ./config
COPY data ./data

EXPOSE 8000
CMD ["uvicorn", "alpha_workbench.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
