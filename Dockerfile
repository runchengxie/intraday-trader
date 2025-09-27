# --- Stage 1: Builder ---
FROM python:3.10 AS builder

# Set the working directory
WORKDIR /app

# Install uv first, then use it for everything else
RUN pip install uv

# Copy only the files needed to install dependencies first.
COPY pyproject.toml LICENSE.txt README.md /app/
COPY src /app/src

# Install dependencies and create a wheel using uv (faster)
# The --system flag tells uv to install into the system Python, which is correct for this Docker context.
RUN uv build --wheel -o dist .

# --- Stage 2: Runner ---
# Use a slim image for the final stage to reduce size.
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH /app

# Install uv in the runner stage as well
RUN pip install uv

# Copy the built wheel from the builder stage
COPY --from=builder /app/dist /wheels/

# Copy the entrypoint scripts
COPY src/patf_trading_framework/scripts/ /app/scripts/

# Copy the configuration file
COPY config.yml /app/config.yml

# Install the package from the wheel file using uv
# --no-cache is uv's default, so we don't need --no-cache-dir
RUN uv pip install --system /wheels/*.whl

# Grant execute permissions to the scripts if needed (good practice)
RUN chmod +x /app/scripts/*.py

# Set the default command to run when the container starts.
CMD ["run-live"]