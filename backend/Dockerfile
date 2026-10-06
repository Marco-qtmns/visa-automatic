FROM python:3.13.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY deployment/backend-runtime-identity.env /tmp/backend-runtime-identity.env
RUN . /tmp/backend-runtime-identity.env \
    && groupadd --gid "$BACKEND_RUNTIME_GID" visaautomatic \
    && useradd --uid "$BACKEND_RUNTIME_UID" --gid visaautomatic --create-home --shell /usr/sbin/nologin visaautomatic \
    && rm /tmp/backend-runtime-identity.env

COPY requirements.deploy.txt /app/requirements.deploy.txt
RUN python -m pip install --requirement /app/requirements.deploy.txt

COPY backend /app/backend
COPY canada /app/canada
COPY templates/canada /app/templates/canada
COPY deployment/environment-contract.json /app/deployment/environment-contract.json
COPY deployment/backend-entrypoint.sh /usr/local/bin/visa-backend-entrypoint

RUN chmod 0555 /usr/local/bin/visa-backend-entrypoint \
    && chown -R visaautomatic:visaautomatic /app

USER visaautomatic

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/visa-backend-entrypoint"]
