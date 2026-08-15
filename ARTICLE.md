# Weekend Creative Challenge: Dog or Not: Lite

`#creative-expression` `#challenge`

> Ready to publish. Every number here was measured against the deployed
> service, not estimated. Not yet posted to Builder Center.

**Live: https://dog-or-not-lite.6wpv8vensby5c.us-east-1.cs.amazonlightsail.com/**
**Source: https://github.com/xbill9/dog-or-not-lite**

---

## Vision and what the app does

You hold something up to your webcam and press one button. A cold, procedural
voice-of-the-machine tells you whether it is a dog. If it is, it barks.

That is the whole app. The creative output is the *verdict*: a
threat-assessment terminal that has been pointed at dogs and does not know it
is making a joke. The humour is entirely in the deadpan — the scanner reports
`FELINE INTRUSION — scanner integrity lost` in exactly the tone it uses for
everything else, and never once acknowledges that any of this is funny.

The interesting design decision is the one that makes it more than a classifier:

**A wolf is not a dog.** Neither is a coyote, a fox, a plush one, a bronze
statue, a cartoon, or a person in a dog costume. That is a *choice* rather than
a fact, and it is the choice that makes the thing worth building. "Is this a
dog" is solved zero-shot by any modern vision model — there is nothing to
measure and nothing to get wrong. Draw the line at *living domestic dog* and
suddenly there are twenty genuinely hard images and a real question about
whether the model understood the rule or just pattern-matched "dog-shaped".

The second rule keeps it usable: judge **the subject depicted, never the medium
carrying it**. Most people testing this will hold up a photo on their phone, so
a photograph of a real dog is a dog. Only the thing *in* the picture counts.

## How I built it

This is a deliberate reduction of a bigger app. The original **Dog or Not**
streams webcam video *and* microphone audio to a live multimodal model over a
bidirectional WebSocket, with browser-local wake-word detection, a live
telemetry HUD, and a session-review panel. About 3,000 lines of client code.

The weekend brief said "start simple: a focused app that does one creative
thing well". So the exercise was subtraction: what is the smallest thing that
still tells the joke?

Everything that made the original hard — streaming, turn-taking, voice activity
detection, session lifecycle — existed to serve a live *conversation*. Take the
conversation away and none of it is needed. What survives is the part the demo
was always actually about: a typed verdict from a vision model.

So: one button, one frame, one HTTP request, one verdict.

### The verdict is a tool call, not prose

The single decision I would keep in any rebuild. The model is never asked to
write "DOG" for me to string-match. It is handed a typed schema and made to
fill it in:

```python
report_verdict(is_dog=False, confidence=84, subject="grey wolf")
```

Bedrock's Converse API takes a `toolConfig`, and setting
`toolChoice: {"tool": {"name": "report_verdict"}}` *forces* the call. Every
image comes back in the same shape — including the ones the model is unsure
about, which is precisely when free-text output gets creative and a parser gets
it wrong. `is_dog` arrives as a boolean because it was declared as one.

### Building the UI with no credentials and no bill

`MOCK=1` short-circuits the Bedrock call and cycles four canned verdicts. The
entire frontend was built and checked against it — no model access, no spend,
and, more usefully, on-demand access to the `NOT A DOG` and `FELINE INTRUSION`
states without going and finding a wolf.

It also caught the one real bug in the UI. The confidence meter had
`transition: width 0.5s, background 0.3s`, and the background transition left
the bar showing the *previous* verdict's colour indefinitely — green under
`NOT A DOG`, red under `FELINE INTRUSION` — while the verdict text, which had
no transition, switched correctly. I only caught it because I could fire all
three states back to back in two seconds. A state indicator should snap to the
state; only the fill level was ever worth animating.

### Measuring it instead of trusting it

`check.py` posts 20 fixtures to the running service and scores `is_dog` against
hand-checked answers. Two things make it worth having:

The fixtures are stored at **640×480 q70 — the exact format the browser
sends** — so the harness exercises the same payload the real client does, not
a pristine 4000px original the app will never see.

And the expectations were **verified by eye before being committed**. Generate
the input, never the expectation. An eval whose ground truth came out of a
model is measuring agreement, not accuracy.

Result against the deployed service: **20/20 correct, median 880 ms per scan**
(20/20 and 831 ms running locally). Nova Lite got every wolf,
every fox, both cats and both bronze statues right, and named the breeds
unprompted — "beagle dog", "corgi dog", "german shepherd". The one thing I would
not claim from this is that the rule is *robust*: 20 clean, well-lit,
subject-fills-frame images is a smoke test, not a benchmark. It tells me the
prompt works and the plumbing is right.

## AWS services used, and the architecture

Two services. That is the entire architecture.

```
browser ──HTTPS──> Lightsail container service ──> Amazon Bedrock
 camera             (nano, 1 node, FastAPI)          Nova Lite
 or upload           serves the page AND              vision + tool use
                     the /api/scan route
```

**Amazon Bedrock (Amazon Nova Lite)** — the classifier. Nova Lite is the
cheapest Bedrock model that takes an image *and* supports tool use, which is
exactly the two things this needs.

**Amazon Lightsail (container service)** — the hosting, and genuinely the whole
of it. One container service on the `nano` power tier, one node. It gives me a
public HTTPS endpoint with a managed certificate and a health check, and I did
not create a load balancer, an S3 bucket, an API Gateway, or a CloudFront
distribution. `deploy.sh` builds the image, pushes it to the service's own
registry, and creates a deployment; re-running it ships a new version to the
same URL.

**AWS IAM** — one user, scoped to `bedrock:InvokeModel` on one model family.

## What I learned

**Lightsail container services have no IAM task role.** This was the real
surprise. On ECS or Lambda you attach a policy to a role and the SDK picks up
credentials automatically. Lightsail has nothing to attach to, so the container
needs a genuine access key passed as an environment variable. That is a real
security cost and the honest thing is to name it rather than hide it, so
`iam-setup.sh` creates a user that can call `InvokeModel` on one model family
and can do *nothing else* in the account. The key never enters the repo, the
image, or a command line.

**Cross-region inference profiles need broader IAM than you would guess.**
Invoking `us.amazon.nova-lite-v1:0` is not a call to one region — the profile
routes across several, and Bedrock checks `InvokeModel` against the underlying
foundation-model ARN in *each* of them.

I tested this rather than assuming it. With the policy pinned to `us-east-1`
only, a call made *to* `us-east-1` fails like this:

```
AccessDeniedException: User: arn:aws:iam::…:user/dog-or-not-lite is not
authorized to perform: bedrock:InvokeModel on resource:
arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0
```

`us-west-2` — a region I never asked for and never configured. The policy needs
the inference-profile ARN *and* a wildcard-region foundation-model ARN. If you
are debugging a Bedrock `AccessDeniedException` that names the wrong region,
this is why.

**`--platform linux/amd64` is not optional.** Lightsail nodes are x86. An arm64
image builds fine, pushes fine, deploys fine, and then crash-loops with an exec
format error that says nothing about architecture.

**Subtraction is a design skill.** The reduced version is not a worse version
of the streaming one — for *this* joke it is a better one. The live build makes
you grant a microphone and wait for a session; this one is a link you can send
someone, and they get the punchline in about a second.

## Links

- **Live app:** https://dog-or-not-lite.6wpv8vensby5c.us-east-1.cs.amazonlightsail.com/
- **Source:** https://github.com/xbill9/dog-or-not-lite

Fixture images are from Wikimedia Commons under their respective licences; full
attribution is in `fixtures/ATTRIBUTION.md`. Bark sound effects generated with
ElevenLabs.
