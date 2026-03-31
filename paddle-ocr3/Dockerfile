# Dockerfile — PaddleOCR 3.0 (PP-OCRv5, Korean)
FROM ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddle:3.0.0

RUN pip install "paddleocr==3.4.0" boto3

# Skip remote model-source connectivity check on startup
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

WORKDIR /paddle

COPY run_ocr.py .

CMD ["tail", "-f", "/dev/null"]
