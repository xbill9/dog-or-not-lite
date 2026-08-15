"""
Dog or Not: Lite -- one FastAPI process, one Bedrock call, one verdict.

The full version of this scanner streams webcam video and microphone audio to a
live multimodal model over a bidirectional WebSocket. This is the same joke with
the plumbing removed: you press a button, one JPEG goes over one HTTP request,
and Amazon Nova Lite answers with a tool call.

The verdict is a TOOL CALL, not prose to be parsed. That is the one piece of the
original design worth carrying over -- `is_dog` arrives as a boolean because the
model was handed a typed schema, so the UI never has to guess whether "that's
definitely a dog!" means yes.
"""

import base64
import binascii
import json
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dogornot")

# Nova Lite is the cheapest Bedrock model that takes an image and supports tool
# use, which is exactly the two things this needs. The `us.` prefix is an
# inference profile: several regions only serve Nova through one, and invoking
# the bare `amazon.nova-lite-v1:0` there fails with a ValidationException that
# does not mention profiles. Override with MODEL_ID if your region differs.
MODEL_ID = os.getenv("MODEL_ID", "us.amazon.nova-lite-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
PORT = int(os.getenv("PORT", "8080"))

# MOCK=1 answers every scan locally, cycling through the three outcomes. It
# exists so the page can be developed and checked with no credentials, no model
# access and no bill -- which is also the only way to exercise the NOT A DOG and
# feline paths on demand rather than by finding a wolf.
MOCK = os.getenv("MOCK", "").lower() in {"1", "true", "yes"}

# A JPEG from the browser at 640x480 q70 lands around 40-60 KB; base64 inflates
# it by a third. 6 MB is far above anything the client sends and far below
# Bedrock's own image limit, so it rejects a junk payload before paying for a
# model call.
MAX_IMAGE_BYTES = 6 * 1024 * 1024

# One client for the process. boto3 clients are thread-safe and building one
# costs a credential lookup, which is not something to do per request.
#
# Built lazily: under MOCK there may be no credentials at all, and constructing
# the client eagerly would fail at import on a machine that has never run
# `aws login`.
_bedrock = None


def bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=Config(
                retries={"max_attempts": 2, "mode": "standard"},
                read_timeout=30,
                connect_timeout=5,
            ),
        )
    return _bedrock


# Deliberately the awkward cases, in the order that makes a demo readable: the
# happy path, the one that makes the classification rule interesting, and the
# easter egg.
MOCK_VERDICTS = [
    {"is_dog": True, "confidence": 97, "subject": "golden retriever", "is_cat": False},
    {"is_dog": False, "confidence": 84, "subject": "grey wolf", "is_cat": False},
    {"is_dog": False, "confidence": 91, "subject": "tabby cat", "is_cat": True},
    {"is_dog": False, "confidence": 62, "subject": "plush dachshund", "is_cat": False},
]
_mock_index = 0

# The typed schema is the whole point. The model does not write "DOG" for us to
# string-match; it fills in a boolean.
TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "report_verdict",
                "description": (
                    "Report whether the subject presented to the scanner is a "
                    "dog. Call this exactly once, for every image, always."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "is_dog": {
                                "type": "boolean",
                                "description": (
                                    "True only for an actual living dog. False "
                                    "for a wolf, coyote, fox, plush toy, "
                                    "statue, drawing, cartoon or costume."
                                ),
                            },
                            "confidence": {
                                "type": "integer",
                                "description": "0-100.",
                            },
                            "subject": {
                                "type": "string",
                                "description": (
                                    "What it actually is, three words or "
                                    "fewer: 'golden retriever', 'grey wolf', "
                                    "'ceramic figurine'."
                                ),
                            },
                            "is_cat": {
                                "type": "boolean",
                                "description": (
                                    "True if the subject is a cat. This is a "
                                    "separate field because a cat is not "
                                    "merely a non-dog."
                                ),
                            },
                        },
                        "required": ["is_dog", "confidence", "subject", "is_cat"],
                    }
                },
            }
        }
    ],
    # Nova will happily narrate instead of calling a tool if you let it. Forcing
    # the tool means every image produces a verdict in the same shape, including
    # the ones the model is unsure about.
    "toolChoice": {"tool": {"name": "report_verdict"}},
}

SYSTEM_PROMPT = """You are a Canine Verification Interrogator: a cold, \
procedural threat-assessment system whose entire job is deciding whether the \
subject presented to it is a dog.

Judge the SUBJECT DEPICTED, never the medium carrying it. Subjects are normally \
held up to a webcam, often as a photograph on a phone screen or on paper. That \
is the expected mode of operation and never affects the verdict: a photograph \
of a real dog IS a dog.

is_dog is FALSE for a wolf, coyote, fox, plush toy, statue, drawing, cartoon or \
costume, however the subject reaches you. Report what it actually is in \
`subject` regardless.

If the image is too blurry, dark or empty to judge, set is_dog false, set \
confidence low, and say so in `subject` ("unclear", "empty frame").

Call report_verdict exactly once. Do not write any prose."""


class ScanRequest(BaseModel):
    image: str = Field(..., description="Base64-encoded JPEG, no data: prefix.")


class Verdict(BaseModel):
    is_dog: bool
    confidence: int
    subject: str
    is_cat: bool = False


app = FastAPI(title="Dog or Not: Lite")


def _decode_image(image_b64: str) -> bytes:
    """Strip an optional data: URL prefix and decode, or 400."""
    if "," in image_b64[:64]:
        image_b64 = image_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="image is not valid base64"
        ) from exc
    if not raw:
        raise HTTPException(status_code=400, detail="image is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="image too large")
    return raw


def _extract_verdict(response: dict) -> Verdict:
    """Pull the report_verdict call out of a Converse response."""
    content = response.get("output", {}).get("message", {}).get("content", [])
    for block in content:
        use = block.get("toolUse")
        if use and use.get("name") == "report_verdict":
            return Verdict(**use.get("input", {}))
    # toolChoice makes this close to unreachable, but "close to" is not "never",
    # and a 502 naming the cause beats a KeyError traceback.
    raise HTTPException(status_code=502, detail="model did not return a verdict")


@app.post("/api/scan", response_model=Verdict)
def scan(req: ScanRequest) -> Verdict:
    raw = _decode_image(req.image)

    if MOCK:
        global _mock_index
        verdict = Verdict(**MOCK_VERDICTS[_mock_index % len(MOCK_VERDICTS)])
        _mock_index += 1
        log.info(
            "MOCK %s: %s", "DOG" if verdict.is_dog else "NOT A DOG", verdict.subject
        )
        return verdict

    try:
        response = bedrock().converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": "jpeg", "source": {"bytes": raw}}},
                        {"text": "Identify the subject."},
                    ],
                }
            ],
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"maxTokens": 256, "temperature": 0.2},
        )
    except ClientError as exc:
        # AccessDeniedException here almost always means model access has not
        # been granted for Nova in this account/region -- the console calls it
        # "Model access", and it is per-region.
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        log.error("bedrock %s: %s", code, exc)
        raise HTTPException(status_code=502, detail=f"bedrock error: {code}") from exc
    except BotoCoreError as exc:
        log.error("bedrock transport error: %s", exc)
        raise HTTPException(status_code=502, detail="bedrock unreachable") from exc

    verdict = _extract_verdict(response)
    usage = response.get("usage", {})
    log.info(
        "%s: %s (%d%%) in=%s out=%s",
        "DOG" if verdict.is_dog else "NOT A DOG",
        verdict.subject,
        verdict.confidence,
        usage.get("inputTokens"),
        usage.get("outputTokens"),
    )
    return verdict


@app.get("/api/config")
def config() -> JSONResponse:
    """Non-secret runtime config, so the page can name the model it is using."""
    return JSONResponse(
        {"model": "MOCK (no model)" if MOCK else MODEL_ID, "region": AWS_REGION}
    )


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Lightsail polls this to decide whether a deployment came up."""
    return JSONResponse({"ok": True})


@app.get("/")
def index() -> FileResponse:
    return FileResponse("static/index.html")


# Mounted last: a StaticFiles at "/" would otherwise shadow every route above.
app.mount("/", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
