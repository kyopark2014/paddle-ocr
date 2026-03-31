import sys
import os
import subprocess
import json
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError


_MODE = os.environ.get("OCR_MODE", "full")  # "full" | "light"

PROJECT_ROOT = Path(__file__).parent.parent

if _MODE == "light":
    DOCKER_IMAGE = "my-paddleocr-light"
    CONTAINER_NAME = "my-paddleocr-light-daemon"
    DOCKERFILE_DIR = PROJECT_ROOT / "paddle-light"
    BUILD_CONTEXT = DOCKERFILE_DIR
    PLATFORM_ARGS = ["--platform", "linux/amd64"]
    OCR_EXEC_CMD = ["python", "run_ocr.py"]
else:
    # Rust/MNN-based image — builds natively for the host architecture
    DOCKER_IMAGE = "my-paddleocr"
    CONTAINER_NAME = "my-paddleocr-daemon"
    DOCKERFILE_DIR = PROJECT_ROOT / "paddle-ocr"
    BUILD_CONTEXT = DOCKERFILE_DIR
    PLATFORM_ARGS = []
    OCR_EXEC_CMD = ["/paddle/cli"]

AWS_CREDENTIALS_PATH = Path.home() / ".aws"
CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def upload_to_s3(local_path: str, config: dict) -> str:
    """Upload a local file to S3 and return the s3:// path. Skips upload if the file already exists."""
    bucket = config["s3_bucket"]
    filename = Path(local_path).name
    key = f"ocr/{filename}"

    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3", region_name=config["region"])

    try:
        s3.head_object(Bucket=bucket, Key=key)
        print(f"S3 file already exists, skipping upload: s3://{bucket}/{key}", file=sys.stderr)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            try:
                print(f"Uploading to S3: {local_path} -> s3://{bucket}/{key}", file=sys.stderr)
                s3.upload_file(local_path, bucket, key)
            except (ClientError, BotoCoreError) as upload_err:
                raise RuntimeError(f"S3 upload failed: {upload_err}")
        else:
            raise RuntimeError(f"S3 check failed: {e}")

    return f"s3://{bucket}/{key}"


def _build_cmd() -> list[str]:
    """Construct the docker build command."""
    cmd = ["docker", "build"] + PLATFORM_ARGS + [
        "-f", str(DOCKERFILE_DIR / "Dockerfile"),
        "-t", DOCKER_IMAGE,
        str(BUILD_CONTEXT),
    ]
    return cmd


def build_image() -> None:
    """Build the Docker image."""
    print(f"Building Docker image '{DOCKER_IMAGE}'...", file=sys.stderr)
    result = subprocess.run(_build_cmd(), text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Docker build failed with exit code {result.returncode}")


def exit_with_build_instructions(reason: str) -> None:
    """Print the docker build command and exit."""
    print(f"\n[Error] {reason}", file=sys.stderr)
    print("\nRun the following command to build the Docker image first:\n", file=sys.stderr)
    print(f"  {' '.join(_build_cmd())}\n", file=sys.stderr)
    sys.exit(1)


def is_container_running() -> bool:
    """Check if the daemon container is currently running via docker ps."""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={CONTAINER_NAME}", "--filter", "status=running", "-q"],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def start_container() -> None:
    """Start the daemon container. Builds the image first if missing or not runnable."""
    if not AWS_CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"AWS credentials directory not found: {AWS_CREDENTIALS_PATH}\n"
            "Run 'aws configure' to set up your credentials."
        )

    def _run_cmd() -> list[str]:
        config = load_config()
        cmd = [
            "docker", "run", "-d",
        ] + PLATFORM_ARGS + [
            "--pull", "never",
            "--name", CONTAINER_NAME,
            "-v", f"{AWS_CREDENTIALS_PATH}:/root/.aws:ro",
            "-e", f"AWS_DEFAULT_REGION={config['region']}",
        ]
        profile = os.environ.get("AWS_PROFILE")
        if profile:
            cmd += ["-e", f"AWS_PROFILE={profile}"]
        cmd.append(DOCKER_IMAGE)
        return cmd

    print(f"Starting container '{CONTAINER_NAME}'...", file=sys.stderr)
    result = subprocess.run(_run_cmd(), capture_output=True, text=True)

    if result.returncode != 0:
        stderr = result.stderr
        if "Unable to find image" in stderr or "No such image" in stderr:
            exit_with_build_instructions("Docker image not found.")
        if "does not provide the specified platform" in stderr:
            exit_with_build_instructions(
                f"Image '{DOCKER_IMAGE}' exists but was built for a different platform.\n"
                "  Rebuild with --platform linux/amd64."
            )
        raise RuntimeError(f"Failed to start container:\n{stderr}")


def ensure_container() -> None:
    """Ensure the daemon container is running. Start it if not."""
    if is_container_running():
        print(f"Container '{CONTAINER_NAME}' is already running.", file=sys.stderr)
        return

    # Remove stopped container with the same name if it exists
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
    )
    start_container()


def run_ocr(input_path: str) -> None:
    config = load_config()

    if input_path.startswith("s3://"):
        s3_url = input_path
    else:
        local_path = Path(input_path)
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {input_path}")
        s3_url = upload_to_s3(str(local_path), config)

    ensure_container()

    print(f"Running OCR on: {s3_url}", file=sys.stderr)

    proc = subprocess.run(
        ["docker", "exec", CONTAINER_NAME] + OCR_EXEC_CMD + [s3_url],
        capture_output=True, text=True,
    )

    if proc.returncode != 0:
        print(f"[Docker error]\n{proc.stderr}", file=sys.stderr)
        sys.exit(proc.returncode)

    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    # Extract JSON from stdout (native MNN libraries may print extra lines)
    stdout = proc.stdout
    start = stdout.find('{')
    end = stdout.rfind('}') + 1
    if start == -1 or end == 0:
        raise RuntimeError(f"No JSON output from OCR process. stdout: {stdout[:200]}")
    result = json.loads(stdout[start:end])
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  Local file: python run.py /path/to/image.jpg", file=sys.stderr)
        print("  S3 path:    python run.py s3://<bucket>/<key>", file=sys.stderr)
        sys.exit(1)

    output = run_ocr(sys.argv[1])
    if output:
        print(output.get("result", ""))
