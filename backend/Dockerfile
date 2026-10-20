# The image for the local stack (docker-compose.yml): Serena, the CollectionSpace simulator and the local tools.
# The production image is deploy/Dockerfile (pull request 17), without the simulator or the tools.
# The base image comes from Amazon ECR Public's copy of the Docker official image, as in deploy/Dockerfile (no Docker
# Hub rate limits).
FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app
# The pinned dependencies first, checked against their hashes, so a change to the code alone reuses this layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY pyproject.toml ./
COPY serena ./serena
COPY fakecspace ./fakecspace
COPY devtools ./devtools
# Serena itself downloads nothing: its dependencies and setuptools came from requirements.txt.
# Make the code readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && chmod -R a+rX /app && useradd -r -u 10001 serena
USER serena
EXPOSE 8000
CMD ["uvicorn", "serena.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
