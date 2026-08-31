FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LEDGERBOX_ROOT=/var/lib/ledgerbox \
    LEDGERBOX_CONFIG=/etc/ledgerbox/config.yaml

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && mkdir -p /var/lib/ledgerbox/data /var/lib/ledgerbox/inbox /etc/ledgerbox

EXPOSE 8765

CMD ["python", "-m", "ledgerbox", "api", "--host", "0.0.0.0", "--port", "8765"]
