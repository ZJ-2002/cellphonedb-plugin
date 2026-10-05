# CellPhoneDB official stack, tier-① wrapper (MIT license, redistributable).
# Package and database are BOTH pinned: the digest of this image therefore pins
# the official algorithm version AND the curated interaction database.
FROM docker.io/library/python:3.11-slim

ARG http_proxy=
ARG https_proxy=
ARG no_proxy=localhost,127.0.0.1

RUN pip install --no-cache-dir cellphonedb==5.0.1

# Bake the curated database at build time (nodes run network-isolated).
# v5 code is compatible with database >= 4.1.0; pin the current v5.0.0 data.
RUN mkdir -p /opt/cellphonedb \
 && python -c "from cellphonedb.utils import db_utils; db_utils.download_database('/opt/cellphonedb', 'v5.0.0')" \
 && ls -la /opt/cellphonedb/

# Driver: I/O translation only — feeds engine tables/h5ad to the official API.
COPY driver.py /opt/autonomics/driver.py

ENV CPDB_ROOT=/opt/cellphonedb
WORKDIR /workdir
ENTRYPOINT ["python3", "/opt/autonomics/driver.py"]
