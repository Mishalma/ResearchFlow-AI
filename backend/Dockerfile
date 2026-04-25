FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV HF_HOME=/opt/huggingface
ENV HF_HUB_CACHE=/opt/huggingface/hub

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-fonts-recommended \
        texlive-latex-extra \
        texlive-publishers \
        texlive-science \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ARG PRELOAD_HUMANIZER_MODEL=false
ARG HUMANIZER_HF_MODEL_ID=AventIQ-AI/t5-paraphrase-generation
ARG PRELOAD_DESKLIB_MODEL=false
ARG AI_DETECTOR_MODEL_ID=desklib/ai-text-detector-academic-v1.01
ARG AI_DETECTOR_MODEL_PATH=/tmp/papereasy-models/desklib-ai-text-detector-academic-v1.01
RUN mkdir -p "${HF_HUB_CACHE}" \
    && if [ "${PRELOAD_HUMANIZER_MODEL}" = "true" ]; then \
        python -c "from transformers import AutoModelForSeq2SeqLM, AutoTokenizer; model='${HUMANIZER_HF_MODEL_ID}'; AutoTokenizer.from_pretrained(model, use_fast=False); AutoModelForSeq2SeqLM.from_pretrained(model)"; \
    fi \
    && if [ "${PRELOAD_DESKLIB_MODEL}" = "true" ]; then \
        python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='${AI_DETECTOR_MODEL_ID}', local_dir='${AI_DETECTOR_MODEL_PATH}', local_dir_use_symlinks=False)"; \
    fi

COPY . /app

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
