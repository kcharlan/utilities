FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/

EXPOSE 4141

CMD ["uvicorn", "llm_proxy.main:app", "--host", "0.0.0.0", "--port", "4141"]
