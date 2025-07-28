
FROM debian:buster

RUN sed -i 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' /etc/apt/sources.list && \
    sed -i 's|http://deb.debian.org/debian-security|http://archive.debian.org/debian-security|g' /etc/apt/sources.list && \
    apt-get update

RUN apt-get install -y curl 

ENV UV_INSTALL_DIR="/usr/bin" UV_PYTHON_INSTALL_DIR="/usr/bin" UV_TOOL_DIR="/usr/bin" UV_TOOL_BIN_DIR="/usr/bin" UV_CACHE_DIR="/opt/uv_cache"
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
        uv python install cpython-3.13.5-linux-x86_64-gnu

ADD . /opt/virus-taxonomy-mappings
RUN cd /opt/virus-taxonomy-mappings && uv sync --frozen

ENTRYPOINT [ "/opt/virus-taxonomy-mappings/.venv/bin/python3", "/opt/virus-taxonomy-mappings/src/map.py" ]




