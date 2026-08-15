# Dog or Not: Lite

A scanner with one job: you hold something up to the camera, press **SCAN**, and
it tells you whether it is a dog. If it is, it barks.

It is deliberately not charming about it. The scanner is a cold
threat-assessment system that happens to have been pointed at dogs, and the
entire joke is that it does not know it is making one.

> Built for the [AWS Weekend Challenge: Build a Creative App](https://builder.aws.com/content/3HkKlGRPcyks0rQpYVUVY9veCX0/weekend-challenge-build-a-creative-app).

**Live: https://dog-or-not-lite.6wpv8vensby5c.us-east-1.cs.amazonlightsail.com/**

Press START CAMERA and hold something up, or UPLOAD an image. Scored 20/20 on
the fixture set against the deployed service, median 880 ms per scan.

## What "Lite" means

This is a deliberate reduction of [Dog or Not](https://github.com/xbill9/way-back-home),
which streams webcam video and microphone audio to a live multimodal model over
a bidirectional WebSocket, with local wake-word detection, a telemetry HUD, and
a session-review panel. That version is about 3,000 lines of client code.

This one is a button. One frame, one HTTP request, one verdict:

```
webcam or upload ──→ 640x480 JPEG ──→ POST /api/scan
                                          │
                                          ├─→ Amazon Bedrock (Nova Lite)
                                          │      report_verdict(...)
                                          ▼
                                   DOG / NOT A DOG + bark
```

Everything that made the original hard — streaming, turn-taking, voice activity
detection, session lifecycle — was there to serve the live conversation. Take
the conversation away and none of it is needed. What survives is the part the
demo was always actually about: a typed verdict from a vision model.

## The verdict is a tool call

The model is not asked to write "DOG" for us to string-match. It is handed a
typed schema and made to fill it in:

```python
report_verdict(is_dog=False, confidence=84, subject="grey wolf")
```

`toolChoice` forces the call, so every image produces a verdict in the same
shape — including the ones the model is unsure about, which is exactly when
free-text output gets creative and a parser gets it wrong.

A wolf is not a dog. Neither is a coyote, a fox, a plush one, a statue, a
drawing, or a person in a costume. That is a choice rather than a fact, and it
is the choice that makes the eval interesting instead of a formality: "is this a
dog" is otherwise solved zero-shot and there is nothing to measure.

Judging is on the **subject depicted, never the medium**. A photo of a real dog
held up on a phone screen is a dog.

Present a cat and the scanner reports a containment failure. It is not rated for
cats.

## Running it

```bash
./run.sh                 # http://127.0.0.1:8080, real Bedrock calls
MOCK=1 ./run.sh          # no credentials, no bill, cycles the four outcomes
```

`MOCK=1` is how the UI was built. It is also the only way to see the NOT A DOG
and FELINE INTRUSION states on demand rather than by going and finding a wolf.

## Deploying it

One Lightsail container service. No load balancer, no bucket, no API Gateway,
no CDN to invalidate.

```bash
./iam-setup.sh           # scoped IAM user, key written to ~/dogornot-lite.key
./deploy.sh              # build, push, deploy, print the URL
```

`deploy.sh` is idempotent — re-running it ships a new deployment version to the
same service on the same URL.

**Lightsail container services have no IAM task role.** Unlike ECS or Lambda,
there is nothing to attach a policy to, so the container needs a real access key
passed as an environment variable. That is the one genuine security cost of
choosing Lightsail, and the mitigation is scope: `iam-setup.sh` creates a user
that can call `InvokeModel` on one model family and can do nothing else in the
account. The key never enters the repo, the image, or a command line.

## Checking it

```bash
./check.py                                    # against localhost
./check.py --url https://<service>.amazonaws.com --min-rate 0.9
```

20 images, each with a hand-checked answer in `fixtures/fixtures.json`. The
fixtures are stored at 640x480 q70 — the exact format the browser sends — so the
harness exercises the same payload the real client does.

The expectations were verified by eye before being committed. Generate the
input, never the expectation.

Fixtures are from Wikimedia Commons; see `fixtures/ATTRIBUTION.md`.

## Layout

| Path | What it is |
|---|---|
| `app.py` | The whole backend. One route that matters. |
| `static/` | The whole frontend. Three files, no build step. |
| `check.py` | Fixture accuracy harness, stdlib only. |
| `deploy.sh` | Build → push → deploy to Lightsail. |
| `iam-setup.sh` | Least-privilege IAM user for the container. |

## Credit

The classification rules, the persona, the bark pack and the fixture set come
from the original **Dog or Not**. Sound effects generated with
[ElevenLabs](https://elevenlabs.io).
