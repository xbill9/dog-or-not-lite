---
title: I rebuilt my over-engineered weekend project as a single button
published: false
description: The original streamed webcam video and microphone audio to a live multimodal model over a WebSocket. The rebuild is one frame, one Bedrock call, one verdict — and for this joke it is the better app.
tags: aws, ai, python, showdev
cover_image: https://raw.githubusercontent.com/xbill9/dog-or-not-lite/9908242b55f886a7208f8d7dc230044c2f01309d/cover.jpg
---

*Built for the [AWS Weekend Challenge: Build a Creative App](https://builder.aws.com/content/3HkKlGRPcyks0rQpYVUVY9veCX0/weekend-challenge-build-a-creative-app).*

**Live: [Dog or Not: Lite](https://dog-or-not-lite.6wpv8vensby5c.us-east-1.cs.amazonlightsail.com/)** · **Source: [github.com/xbill9/dog-or-not-lite](https://github.com/xbill9/dog-or-not-lite)**

## What I built

You hold something up to your webcam and press one button. A cold, procedural voice-of-the-machine tells you whether it is a dog. If it is, it barks.

That is the entire app. It is deliberately not charming about it — the scanner is a threat-assessment terminal that has been pointed at dogs and does not know it is making a joke. Present a cat and it reports a containment failure. It is not rated for cats.

The interesting part is not the classifier. It is what I removed to get here.

## The subtraction

A fortnight ago I built the same idea the maximal way: webcam video **and** microphone audio streamed to a live multimodal model over a bidirectional WebSocket, browser-local wake-word detection so the mic never hits the wire, a live telemetry HUD, a session-review panel, reconnect logic for a specific 1007 close code. About 3,000 lines of client code.

This challenge said "start simple: a focused app that does one creative thing well." So I asked the opposite question: what is the smallest thing that still tells the joke?

Everything that made the original hard — streaming, turn-taking, voice activity detection, session lifecycle — existed to serve a live *conversation*. Take the conversation away and none of it is load-bearing. What survives is the part the demo was always actually about: a typed verdict from a vision model.

One button. One frame. One HTTP request. One verdict.

Three static files, no build step, no bundler, no framework.

## The rule that makes it measurable

**A wolf is not a dog.** Neither is a coyote, a fox, a plush one, a bronze statue, a cartoon, or a person in a dog costume.

That is a choice rather than a fact, and it is the choice that makes the thing worth building. "Is this a dog" is solved zero-shot by any modern vision model — there is nothing to measure and nothing to get wrong. Draw the line at *living domestic dog* and suddenly there are twenty genuinely hard images and a real question about whether the model understood the rule or just pattern-matched "dog-shaped".

The second rule keeps it usable: judge **the subject depicted, never the medium carrying it**. Most people testing this hold up a photo on their phone, so a photograph of a real dog is a dog. Only the thing *in* the picture counts.

## The verdict is a tool call, not prose

The one decision I would keep in any rebuild. The model is never asked to write "DOG" for me to string-match. It is handed a typed schema and made to fill it in:

```python
report_verdict(is_dog=False, confidence=84, subject="grey wolf")
```

Bedrock's Converse API takes a `toolConfig`, and this *forces* the call:

```python
"toolChoice": {"tool": {"name": "report_verdict"}}
```

Every image comes back in the same shape — including the ones the model is unsure about, which is exactly when free-text output gets creative and a parser gets it wrong. `is_dog` arrives as a boolean because it was declared as one.

## Building the whole UI with no credentials and no bill

`MOCK=1` short-circuits the Bedrock call and cycles four canned verdicts. The entire frontend was built against it: no model access, no spend, and — more usefully — on-demand access to the `NOT A DOG` and `FELINE INTRUSION` states without going and finding a wolf.

It earned its keep by catching the only real UI bug. The confidence meter had:

```css
transition: width 0.5s ease, background 0.3s ease;
```

That `background` transition left the bar showing the **previous** verdict's colour indefinitely — green under `NOT A DOG`, red under `FELINE INTRUSION` — while the verdict text, which had no transition, switched correctly. I found it because I could fire all three states back to back in two seconds and watch them disagree.

A state indicator should snap to the state. Only the fill level was ever worth animating.

## Measuring it instead of trusting it

`check.py` posts 20 fixtures to the running service and scores `is_dog` against hand-checked answers. Two details make it worth having.

The fixtures are stored at **640×480 q70 — the exact format the browser sends**, so the harness exercises the same payload the real client does, not a pristine 4000px original the app will never see.

And the expectations were **verified by eye before being committed**. Generate the input, never the expectation. An eval whose ground truth came out of a model is measuring agreement, not accuracy.

Against the deployed service: **20/20 correct, median 880 ms per scan.** Nova Lite got every wolf, every fox, both cats and both bronze statues, and named breeds unprompted — "beagle dog", "corgi dog", "german shepherd".

I would not claim from this that the rule is *robust*. Twenty clean, well-lit, subject-fills-frame images is a smoke test, not a benchmark. It says the prompt works and the plumbing is right.

## Two AWS things that cost me time

**Lightsail container services have no IAM task role.** On ECS or Lambda you attach a policy to a role and the SDK picks up credentials automatically. Lightsail has nothing to attach to, so the container needs a genuine access key as an environment variable — and those are readable afterwards via `get-container-services`. The mitigation is scope, not secrecy: a user that can call `InvokeModel` on one model family and nothing else in the account.

**A cross-region inference profile is checked against every region it routes to.** With my IAM policy pinned to `us-east-1`, a call made *to* `us-east-1` failed like this:

```
AccessDeniedException: ... not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0
```

`us-west-2` — a region I never asked for and never configured. I only believe this because I narrowed the policy on purpose to see it fail. The policy needs the inference-profile ARN *and* a wildcard-region foundation-model ARN. If you are staring at a Bedrock denial that names the wrong region, that is why.

## The architecture, in full

```
browser ──HTTPS──> Lightsail container service ──> Amazon Bedrock
 camera             (nano, 1 node, FastAPI)          Nova Lite
 or upload           serves the page AND              vision + tool use
                     the /api/scan route
```

Two services. One container, one model, one IAM user. No load balancer, no bucket, no API Gateway, no CDN to invalidate.

## What I actually learned

Subtraction is a design skill, and it is harder than addition because you have to be honest about which complexity was ever doing work.

The reduced version is not a worse version of the streaming one. For *this* joke it is a better one: the live build makes you grant a microphone and wait for a session, while this one is a link you can send someone, and they get the punchline in about a second.

---

*Amazon Nova Lite (`us.amazon.nova-lite-v1:0`) via the Bedrock Converse API, FastAPI on Python 3.13, deployed to an Amazon Lightsail container service (`nano`, scale 1) in us-east-1. Images captured at 640×480 JPEG q70. Fixture images from Wikimedia Commons, attributed in the repo. Bark sound effects generated with [ElevenLabs](https://elevenlabs.io).*
