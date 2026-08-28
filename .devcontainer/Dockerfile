FROM python:3.13-slim AS pypff-builder

# Build a wheel from the immutable libpff Python source distribution.
ARG LIBPFF_VERSION=20231205
ARG LIBPFF_SHA256=06c218be51321b16dc3b835185ee1cd2fa5c2a1ca856e0390c1d6e4ddf329250

# Install the native build dependencies in the builder only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --silent --show-error \
        --output /tmp/libpff-python.tar.gz \
        "https://files.pythonhosted.org/packages/0b/a3/826777491832478f5e1555a16bc9de794ef0264eac53d213340dddae5bd4/libpff-python-${LIBPFF_VERSION}.tar.gz" \
    && printf '%s  %s\n' "$LIBPFF_SHA256" /tmp/libpff-python.tar.gz \
        | sha256sum --check \
    && python -m pip wheel --no-cache-dir --no-deps \
        --wheel-dir /opt/pypff-wheel /tmp/libpff-python.tar.gz

FROM python:3.13-slim

COPY --from=pypff-builder /opt/pypff-wheel /tmp/pypff-wheel

RUN python -m pip install --no-cache-dir /tmp/pypff-wheel/*.whl \
    && python -c "import pypff" \
    && rm -rf /tmp/pypff-wheel

# Install git and other dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv


# Install Backlog.md
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g backlog.md \
    && rm -rf /var/lib/apt/lists/*


# Install OpenCode CLI
RUN curl -fsSL https://opencode.ai/install | bash
