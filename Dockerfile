# Stage 1: Build dependencies with uv
# Uses a minimal Python image
FROM python:3.13.7-slim-bookworm AS builder

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files and install them
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
# RUN uv sync --frozen --no-install-project --no-dev

# Stage 2: Create the final image
# Uses the same base image to minimize size
FROM python:3.13.7-slim-bookworm

# Add uv to the final image for the `uv run` command
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set environment variables for better Python logging and execution
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Create a non-root user for security
RUN groupadd --system appuser && useradd --system -g appuser appuser
USER appuser

# Set working directory
WORKDIR /app

# Copy the dependency environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Add the virtual environment to the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy your application code into the container
COPY src /app/src

# Expose the port on which the app will run
EXPOSE 8000

# Command to run your application using Uvicorn via uv
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
