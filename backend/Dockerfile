# The image for the local stack (docker-compose.yml) and the AWS simulator: Serena, the CollectionSpace simulator (the
# fakecspace package, requirements-sim.txt) and the local tools.
# The production image is deploy/Dockerfile (pull request 17), without the simulator or the tools.
FROM python:3.11-slim-trixie
# eMudhra CA compromise (Oct 2026): take Debian's fixed ca-certificates even if the base image predates it;
# the build fails if the installed version is older than the fix.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1
WORKDIR /app
# The pinned dependencies first, checked against their hashes, so a change to the code alone reuses this layer.
COPY requirements.txt requirements-sim.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt -r requirements-sim.txt
COPY pyproject.toml ./
COPY serena ./serena
COPY devtools ./devtools
# Serena itself downloads nothing: its dependencies and setuptools came from requirements.txt.
# Make the code readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && chmod -R a+rX /app && useradd -r -u 10001 serena
USER serena
EXPOSE 8000
CMD ["uvicorn", "serena.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
