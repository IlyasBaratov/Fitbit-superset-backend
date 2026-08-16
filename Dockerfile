FROM thisisarpanghosh/fitbit-fetch-data:latest

USER root

WORKDIR /app

COPY --chown=appuser:appuser --chmod=0644 requirements.txt /app/requirements-custom.txt

RUN python -m pip install --no-cache-dir -r /app/requirements-custom.txt

COPY --chown=appuser:appuser --chmod=0644 main.py /app/main.py

USER appuser

CMD ["python", "main.py"]
