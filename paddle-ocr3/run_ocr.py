import sys
import json
import tempfile
import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from paddleocr import PaddleOCR

# PaddleOCR 3.0 — PP-OCRv5, Korean
# https://github.com/PaddlePaddle/PaddleOCR
CONFIDENCE_THRESHOLD = 0.7


def parse_s3_path(s3_path: str) -> tuple[str, str]:
    """s3://bucket-name/path/to/file.jpg -> (bucket, key)"""
    if not s3_path.startswith("s3://"):
        raise ValueError(f"Invalid S3 path: {s3_path}")
    path = s3_path[len("s3://"):]
    bucket, _, key = path.partition("/")
    if not bucket or not key:
        raise ValueError(f"Missing bucket or key: {s3_path}")
    return bucket, key


def download_from_s3(s3_path: str, dest_path: str) -> None:
    bucket, key = parse_s3_path(s3_path)
    s3 = boto3.client("s3")
    try:
        s3.download_file(bucket, key, dest_path)
    except ClientError as e:
        raise RuntimeError(f"S3 download failed: {e}")
    except BotoCoreError as e:
        raise RuntimeError(f"AWS error: {e}")


def run_ocr(image_path: str) -> None:
    ocr = PaddleOCR(
        lang="korean",
        ocr_version="PP-OCRv5",
        use_textline_orientation=True,
        text_detection_model_name="PP-OCRv5_server_det",
        text_recognition_model_name="PP-OCRv5_server_rec",
        text_rec_score_thresh=CONFIDENCE_THRESHOLD,
    )

    results = ocr.predict(image_path)

    if not results:
        print(json.dumps({"result": ""}, ensure_ascii=False))
        return

    lines = []
    for res in results:
        texts = res.get("rec_texts", [])
        scores = res.get("rec_scores", [])
        boxes = res.get("dt_polys", [])

        items = [
            {"text": t, "y": b[0][1] if isinstance(b, list) else b.tolist()[0][1]}
            for t, s, b in zip(texts, scores, boxes)
            if t.strip()
        ]
        items.sort(key=lambda x: x["y"])
        lines.extend(item["text"] for item in items)

    print(json.dumps({"result": "\n".join(lines)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_ocr.py s3://<bucket>/<key>", file=sys.stderr)
        print("Example: python run_ocr.py s3://my-bucket/images/sample.jpg", file=sys.stderr)
        sys.exit(1)

    s3_path = sys.argv[1]
    ext = os.path.splitext(s3_path)[-1] or ".jpg"

    with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
        print(f"Downloading from S3: {s3_path}", file=sys.stderr)
        download_from_s3(s3_path, tmp.name)
        print("Running OCR...", file=sys.stderr)
        run_ocr(tmp.name)
