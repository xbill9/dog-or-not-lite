#!/bin/bash
# Run the scanner locally on http://127.0.0.1:8080.
#
# Uses whatever AWS credentials the shell already has -- your own, not the
# deploy user's -- so it needs `aws login` (or an exported key pair) and Bedrock
# model access for Nova in $AWS_REGION.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
export MODEL_ID="${MODEL_ID:-us.amazon.nova-lite-v1:0}"
export PORT="${PORT:-8080}"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "No usable AWS credentials. Run 'aws login' first." >&2
    exit 1
fi

echo "region=$AWS_REGION model=$MODEL_ID"
echo "http://127.0.0.1:$PORT"
exec python app.py
