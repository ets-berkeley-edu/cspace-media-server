# Serena's production image for AWS (D190): the FastAPI app serving the built admin app, and the worker (the same
# image with another command). Build from the repository root (./serena aws deploy does this):
#   docker build --platform linux/arm64 -f deploy/Dockerfile -t serena .
# The local stack doesn't use this image: it runs backend/Dockerfile, which also holds the CollectionSpace simulator
# and the local tools (an AWS environment with the simulator runs that one as its own image, deploy/README.md).
# Base images come from Amazon ECR Public's copies of the Docker official images (no Docker Hub rate limits).

# ---- the admin app: a production build ---------------------------------------------------------------------------
FROM public.ecr.aws/docker/library/node:22.23.4-alpine AS admin
# eMudhra CA compromise (Oct 2026): Node 22.23.4 refuses the compromised CAs itself, but Alpine's system bundle
# (curl, wget, OpenSSL) needs ca-certificates 20261020-r0; the build fails if the bundle still holds the emSign root.
RUN apk add --no-cache --upgrade ca-certificates-bundle \
    && node -e 'const {X509Certificate} = require("crypto"); const pem = require("fs").readFileSync("/etc/ssl/certs/ca-certificates.crt", "utf8").match(/-----BEGIN CERTIFICATE-----[^-]+-----END CERTIFICATE-----/g); if (pem.some(p => new X509Certificate(p).fingerprint256.startsWith("86:A1:EC:BA"))) { console.error("The system CA bundle still holds emSign ECC Root CA - G3"); process.exit(1); }'
WORKDIR /src
COPY admin/package.json admin/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY admin/ ./
RUN npm run build

# ---- the Python app ----------------------------------------------------------------------------------------------
FROM public.ecr.aws/docker/library/python:3.11-slim-trixie
# eMudhra CA compromise (Oct 2026): take Debian's fixed ca-certificates even if the base image predates it;
# the build fails if the installed version is older than the fix.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SERENA_ADMIN_DIST_DIR=/app/admin
WORKDIR /app
# The pinned dependencies first, checked against their hashes, so a change to the code alone reuses this layer.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY backend/pyproject.toml ./
COPY backend/serena ./serena
# Not backend/fakecspace or backend/devtools: the simulator and the local tools never go in this image.
# Serena itself downloads nothing: its dependencies and setuptools came from requirements.txt.
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && useradd -r -u 10001 serena
COPY --from=admin /src/dist ./admin
# Readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN chmod -R a+rX /app
USER serena
EXPOSE 8000
# The app. The worker's task runs: python -m serena.worker
CMD ["uvicorn", "serena.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
