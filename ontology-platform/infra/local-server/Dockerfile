FROM python:3.12.7-slim-bookworm@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY infra/local-server/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock \
    && useradd --uid 10001 --create-home lzo \
    && mkdir -p /var/lib/lzo-local \
    && chown -R lzo:lzo /var/lib/lzo-local
COPY local_server /app/local_server
COPY scripts /app/scripts
COPY config/local-server-mapping.json /app/config/local-server-mapping.json
COPY docs/fish/ontology-review /app/docs/fish/ontology-review
COPY infra/local-server/container-config.json /app/container-config.json
USER lzo
EXPOSE 8792
ENTRYPOINT ["python", "/app/scripts/run_local_server.py", "--config", "/app/container-config.json"]
CMD ["serve"]
