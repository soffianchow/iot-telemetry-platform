FROM python:3.11.15-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml requirements.lock.txt ./
COPY src ./src
COPY schemas ./schemas
RUN pip install --no-cache-dir -r requirements.lock.txt && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home app && mkdir /data && chown app /data
COPY config ./config
COPY tests ./tests
USER app
ENTRYPOINT ["python", "-m", "iot_ops"]
CMD ["simulate", "--config", "config/devices.json"]
