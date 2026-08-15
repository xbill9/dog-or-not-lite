#!/bin/bash
# Build the image and deploy it to an Amazon Lightsail container service.
#
# Lightsail is the whole architecture: one container service, one node, a public
# HTTPS endpoint with a certificate it manages itself. No load balancer, no
# S3 bucket, no API Gateway, no CloudFront distribution to invalidate.
#
# Re-running this is the normal way to ship a change -- it creates a new
# deployment version on the same service and the same URL.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SERVICE_NAME="${SERVICE_NAME:-dog-or-not-lite}"
AWS_REGION="${AWS_REGION:-us-east-1}"
POWER="${POWER:-nano}"
SCALE="${SCALE:-1}"
MODEL_ID="${MODEL_ID:-us.amazon.nova-lite-v1:0}"
KEY_FILE="${KEY_FILE:-$HOME/dogornot-lite.key}"
CONTAINER_NAME="scanner"

export AWS_REGION

say() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }

# ---- preflight -----------------------------------------------------------

if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "No usable AWS credentials. Run 'aws login' first." >&2
    exit 1
fi

if [[ ! -f "$KEY_FILE" ]]; then
    echo "Missing $KEY_FILE. Run ./iam-setup.sh first." >&2
    exit 1
fi

# `aws lightsail push-container-image` is a thin wrapper around a separate
# binary. Without it the push fails with a message that does not obviously say
# "install a plugin", so check up front.
if ! command -v lightsailctl >/dev/null 2>&1; then
    cat >&2 <<'MSG'
The lightsailctl plugin is not installed, and `aws lightsail push-container-image`
cannot work without it. Install it with:

  curl -fsSL "https://s3.us-west-2.amazonaws.com/lightsailctl/latest/linux-amd64/lightsailctl" \
      -o /tmp/lightsailctl
  sudo install -m 755 /tmp/lightsailctl /usr/local/bin/lightsailctl
MSG
    exit 1
fi

ACCESS_KEY_ID=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["id"])' "$KEY_FILE")
SECRET_ACCESS_KEY=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["secret"])' "$KEY_FILE")

# ---- build ---------------------------------------------------------------

say "Building image (linux/amd64)"
# --platform matters on an arm64 laptop: Lightsail nodes are x86, and an arm
# image deploys cleanly and then crash-loops with an exec format error.
docker build --platform linux/amd64 -t "$SERVICE_NAME:latest" .

# ---- service -------------------------------------------------------------

if aws lightsail get-container-services --service-name "$SERVICE_NAME" >/dev/null 2>&1; then
    say "Container service $SERVICE_NAME exists"
else
    say "Creating container service $SERVICE_NAME ($POWER x$SCALE)"
    aws lightsail create-container-service \
        --service-name "$SERVICE_NAME" \
        --power "$POWER" \
        --scale "$SCALE" >/dev/null
fi

say "Waiting for the service to be READY"
for _ in $(seq 1 60); do
    STATE=$(aws lightsail get-container-services --service-name "$SERVICE_NAME" \
        --query 'containerServices[0].state' --output text)
    echo "  state: $STATE"
    [[ "$STATE" == "READY" || "$STATE" == "RUNNING" ]] && break
    if [[ "$STATE" == "DISABLED" || "$STATE" == "FAILED" ]]; then
        echo "Service is $STATE; not deploying." >&2
        exit 1
    fi
    sleep 10
done

# ---- push ----------------------------------------------------------------

say "Pushing image to the service registry"
aws lightsail push-container-image \
    --service-name "$SERVICE_NAME" \
    --label "$CONTAINER_NAME" \
    --image "$SERVICE_NAME:latest"

# Read the reference back rather than scraping it out of the push output: the
# push prints it in prose, and the API returns it as data.
IMAGE_REF=$(aws lightsail get-container-images --service-name "$SERVICE_NAME" \
    --query 'containerImages[0].image' --output text)
say "Image: $IMAGE_REF"

# ---- deploy --------------------------------------------------------------

# Built with python rather than a heredoc so the secret is JSON-escaped rather
# than interpolated, and passed via file:// so it never appears in the process
# list where `ps` would show it.
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
chmod 700 "$TMP_DIR"

CONTAINER_NAME="$CONTAINER_NAME" IMAGE_REF="$IMAGE_REF" MODEL_ID="$MODEL_ID" \
AWS_REGION="$AWS_REGION" ACCESS_KEY_ID="$ACCESS_KEY_ID" \
SECRET_ACCESS_KEY="$SECRET_ACCESS_KEY" TMP_DIR="$TMP_DIR" \
python3 - <<'PY'
import json, os

name = os.environ["CONTAINER_NAME"]
tmp = os.environ["TMP_DIR"]

containers = {
    name: {
        "image": os.environ["IMAGE_REF"],
        "ports": {"8080": "HTTP"},
        "environment": {
            "PORT": "8080",
            "MODEL_ID": os.environ["MODEL_ID"],
            "AWS_REGION": os.environ["AWS_REGION"],
            "AWS_ACCESS_KEY_ID": os.environ["ACCESS_KEY_ID"],
            "AWS_SECRET_ACCESS_KEY": os.environ["SECRET_ACCESS_KEY"],
        },
    }
}

endpoint = {
    "containerName": name,
    "containerPort": 8080,
    "healthCheck": {
        "path": "/healthz",
        "successCodes": "200",
        "intervalSeconds": 10,
        "timeoutSeconds": 4,
        "healthyThreshold": 2,
        "unhealthyThreshold": 3,
    },
}

with open(f"{tmp}/containers.json", "w") as f:
    json.dump(containers, f)
with open(f"{tmp}/endpoint.json", "w") as f:
    json.dump(endpoint, f)
PY

say "Creating deployment"
aws lightsail create-container-service-deployment \
    --service-name "$SERVICE_NAME" \
    --containers "file://$TMP_DIR/containers.json" \
    --public-endpoint "file://$TMP_DIR/endpoint.json" >/dev/null

say "Waiting for the deployment to go ACTIVE (a few minutes)"
for _ in $(seq 1 60); do
    DEPLOY_STATE=$(aws lightsail get-container-services --service-name "$SERVICE_NAME" \
        --query 'containerServices[0].currentDeployment.state' --output text)
    echo "  deployment: $DEPLOY_STATE"
    [[ "$DEPLOY_STATE" == "ACTIVE" ]] && break
    if [[ "$DEPLOY_STATE" == "FAILED" ]]; then
        echo "Deployment FAILED. Container log:" >&2
        aws lightsail get-container-log --service-name "$SERVICE_NAME" \
            --container-name "$CONTAINER_NAME" --query 'logEvents[-40:].message' \
            --output text >&2 || true
        exit 1
    fi
    sleep 15
done

URL=$(aws lightsail get-container-services --service-name "$SERVICE_NAME" \
    --query 'containerServices[0].url' --output text)

say "Live: $URL"
echo "Health: $(curl -fsS "${URL%/}/healthz" || echo 'not answering yet')"
