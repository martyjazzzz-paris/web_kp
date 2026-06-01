FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=15

WORKDIR /app

# Зеркало при медленном pypi.org: docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements-web.txt /app/requirements-web.txt
RUN pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --default-timeout=300 \
    --retries=15 \
    -r /app/requirements-web.txt

COPY . /app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
