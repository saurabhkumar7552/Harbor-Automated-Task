# Build only after separate provisioning approval. No credentials in this image.
FROM node:22-bookworm
ARG CODEX_VERSION
RUN printf '%s\n' "$CODEX_VERSION" | grep -Eq '^[0-9]+[.][0-9]+[.][0-9]+$' \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && mkdir -p /work /codex-home \
    && chown node:node /work /codex-home
USER node
ENV HOME=/home/node CODEX_HOME=/codex-home
WORKDIR /work
ENTRYPOINT ["codex"]
