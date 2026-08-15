#!/bin/bash
# Create the least-privilege IAM user the deployed container runs as.
#
# Lightsail container services have no IAM task role -- unlike ECS or Lambda,
# there is nothing to attach a policy to, so the container needs a real access
# key passed in as an environment variable. That is the one genuine security
# cost of choosing Lightsail here, and the mitigation is scope: this user can
# call InvokeModel on one model family and can do nothing else in the account.
#
# The key is written to ~/dogornot-lite.key, chmod 600, outside the repo.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

USER_NAME="${USER_NAME:-dog-or-not-lite}"
POLICY_NAME="InvokeNovaLite"
KEY_FILE="${KEY_FILE:-$HOME/dogornot-lite.key}"
AWS_REGION="${AWS_REGION:-us-east-1}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "account: $ACCOUNT_ID"

# A cross-region inference profile routes to several regions, and Bedrock checks
# InvokeModel against the underlying foundation-model ARN in *each* of them --
# not just the one you called. Granting only us-east-1 produces an
# AccessDeniedException naming a region you never asked for.
POLICY_DOC=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeNovaLite",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
        "arn:aws:bedrock:*:${ACCOUNT_ID}:inference-profile/us.amazon.nova-lite-v1:0"
      ]
    }
  ]
}
JSON
)

if aws iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
    echo "user $USER_NAME already exists, updating policy"
else
    aws iam create-user --user-name "$USER_NAME" >/dev/null
    echo "created user $USER_NAME"
fi

aws iam put-user-policy \
    --user-name "$USER_NAME" \
    --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_DOC"
echo "attached inline policy $POLICY_NAME"

# IAM allows two keys per user; a re-run should replace rather than fail.
EXISTING=$(aws iam list-access-keys --user-name "$USER_NAME" \
    --query 'AccessKeyMetadata[].AccessKeyId' --output text)
for k in $EXISTING; do
    aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$k"
    echo "deleted old key $k"
done

# umask before the redirect: the file must never exist world-readable, not even
# for the instant between creation and chmod.
umask 077
aws iam create-access-key --user-name "$USER_NAME" \
    --query 'AccessKey.{id:AccessKeyId,secret:SecretAccessKey}' \
    --output json > "$KEY_FILE"
chmod 600 "$KEY_FILE"

echo "wrote $KEY_FILE (chmod 600)"
echo "IAM propagation takes a few seconds; deploy.sh retries."
