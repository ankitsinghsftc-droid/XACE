# Operator-only AG-029 probe image; not a production distribution.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY openai-codex-0.155.1-linux-x64.tgz /opt/codex-runtime.tgz
RUN mkdir /opt/codex && tar -xzf /opt/codex-runtime.tgz -C /opt/codex \
    && ln -s /opt/codex/package/vendor/x86_64-unknown-linux-musl/bin/codex /usr/local/bin/codex \
    && mkdir /capsule /provider && chmod 1777 /provider
ENV CODEX_HOME=/provider
ENV HOME=/provider
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
WORKDIR /capsule
ENTRYPOINT ["codex"]
