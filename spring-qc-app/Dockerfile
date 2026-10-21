FROM python:3.12-slim

# System libraries OpenCV (headless) and ffmpeg (mp4 / RTSP decoding) need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

WORKDIR /app

# PyTorch build. Default is CUDA 12.4 (GPU); the wheels bundle their own CUDA
# runtime, so only the host needs the NVIDIA Container Toolkit - no CUDA base
# image required. For a CPU-only machine, build with:
#   docker compose build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
RUN pip install --index-url ${TORCH_INDEX} torch torchvision

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8001
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
