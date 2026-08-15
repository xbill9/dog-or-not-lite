# The best thing I did to my weekend project was delete most of it

### I spent one weekend building a live-streaming multimodal scanner. I spent the next one rebuilding it as a single button, and the button is better.

![A dark surveillance monitor with a golden retriever framed by cyan reticle brackets.](https://raw.githubusercontent.com/xbill9/dog-or-not-lite/9908242b55f886a7208f8d7dc230044c2f01309d/cover.jpg)

---

There is a particular kind of pride that comes from a hard build, and it is not entirely trustworthy.

The first version of this project streamed webcam video **and** microphone audio to a live multimodal model over a bidirectional WebSocket. It did browser-local wake-word detection so the microphone never touched the wire. It had a telemetry HUD showing uplink and downlink in kilobits per second, a session-review panel that rendered a whole run on a shared time axis, and reconnect logic written specifically for a close code the API throws mid-session with no explanation of which argument it objected to. About three thousand lines of client code.

It tells you whether the thing you are holding up is a dog.

If it is, it barks.

I am genuinely fond of that build. Most of what is hard in it was hard for a real reason — turn-taking, voice activity detection, session lifecycle — and I measured my way through all of it. But a week later a different challenge asked for something "simple: a focused app that does one creative thing well," and I found myself asking a question I had not asked the first time.

What is the smallest thing that still tells the joke?

---

## The thing about all that complexity

Every hard part of the original existed to serve a live *conversation*. The streaming, the barge-in handling, the voice detection, the session that has to be minted fresh each round or the model resumes the last one mid-sentence — all of it is the cost of a machine you can interrupt.

Take the conversation away and none of it is load-bearing.

What survives is the part the demo was always actually about: a typed verdict from a vision model. One frame, one request, one answer.

So the rebuild is a button. Three static files, no build step, no bundler, no framework. You press it, and about eight hundred milliseconds later a cold procedural readout tells you what you are holding.

It is deliberately not charming about it. The scanner is a threat-assessment terminal that has been pointed at dogs and does not know it is making a joke — it reports `FELINE INTRUSION — scanner integrity lost` in exactly the tone it uses for everything else, and never once acknowledges that any of this is funny. The humour is entirely in the flatness. Add a wink and it dies.

---

## The rule is the whole product

The classifier is not interesting. "Is this a dog" is solved zero-shot by any modern vision model; there is nothing to measure and nothing to get wrong.

So I drew the line somewhere harder. **A wolf is not a dog.** Neither is a coyote, a fox, a plush one, a bronze statue, a cartoon, or a person in a dog costume.

That is a choice rather than a fact, and it is the choice that turns a formality into an eval. Suddenly there are twenty genuinely hard images and a real question underneath them: did the model understand the rule, or is it just pattern-matching "dog-shaped"?

A second rule keeps it usable. Judge **the subject depicted, never the medium carrying it** — most people testing this hold up a photo on their phone, so a photograph of a real dog is a dog. Only the thing *in* the picture counts.

Twenty fixtures, every answer checked by eye before it was committed. Against the deployed service it scored twenty out of twenty, median eight hundred and eighty milliseconds, naming breeds unprompted along the way.

I would not call that robust. Twenty clean, well-lit, subject-fills-frame images is a smoke test, not a benchmark — it tells me the prompt works and the plumbing is right, and it would tell me very little about a dog photographed badly at dusk. But it is a real number produced by the real deployment, which is more than most weekend projects can say about themselves.

---

## Never ask a model to write the answer in prose

The one decision I would keep in any rebuild, at any size.

The model is never asked to write "DOG" for me to string-match. It is handed a typed schema and made to fill it in — `is_dog` as a boolean, `confidence` as an integer, `subject` in three words or fewer — and the API is told it *must* call that function rather than narrate.

The failure this prevents is specific. Left to free text, a model is perfectly reliable on the easy images and gets creative exactly on the ambiguous ones — the wolf, the statue, the plush toy — which is precisely where a parser is least able to cope. Forcing the schema means the uncertain cases come back in the same shape as the certain ones, with the uncertainty in a confidence field where it belongs instead of hedged into a sentence.

---

## The bug I would not have found

I built the entire interface against a mock that short-circuits the model call and cycles four canned verdicts. No credentials, no spend, and — more usefully — the ability to fire every state on demand instead of going out and finding a wolf.

It paid for itself immediately. The confidence meter had a CSS transition on its background colour, and that transition left the bar showing the **previous** verdict's colour indefinitely: green under `NOT A DOG`, red under `FELINE INTRUSION`. The verdict text, which had no transition, switched correctly. So the two halves of the same readout disagreed, permanently, and each one looked fine on its own.

You only see that if you can put three verdicts on screen inside two seconds. With a real camera and a real model you would scan a dog, then go find a cat, and by the time you got back the colour would have settled and told you nothing.

A state indicator should snap to the state. Only the fill level was ever worth animating.

---

## Two things the cloud taught me the hard way

I deployed this to a single Amazon Lightsail container service — one container, one model, one narrowly-scoped IAM user, and nothing else. No load balancer, no bucket, no gateway, no CDN.

**Lightsail containers cannot assume an IAM role.** On most AWS compute you attach a policy to a role and credentials appear by magic. Lightsail has nothing to attach to, so the container needs a real access key handed to it as an environment variable — and those are readable after the fact by anyone who can describe the service. There is no way to make that elegant. The only honest response is to scope the key until it is boring: it can invoke one model family and do nothing else in the account.

**And a cross-region inference profile is checked against every region it quietly routes to.** With my policy pinned to one region, a call made *to* that same region failed, naming a completely different one I had never configured. I only believe this because I narrowed the policy deliberately to watch it break. If you are ever staring at a permissions error that names a region you never asked for, that is the reason.

---

## What I am taking from this

Subtraction is a design skill, and it is harder than addition, because it requires being honest about which complexity was ever doing work.

Every hard thing in the original was justified *locally*. Each one solved a real problem that the previous decision had created. None of that is the same as being necessary, and the only way I found out was by building the version that refuses them all and seeing what actually broke.

Nothing broke. What I lost was a scanner you can interrupt mid-sentence, which is a genuinely good thing that this joke does not need. What I gained was a link I can send to someone who will get the punchline in about a second, without granting a microphone or waiting for a session to warm up.

The elaborate version is still the more impressive engineering. The button is the better app.

---

*Amazon Nova Lite via the Bedrock Converse API with forced tool use, FastAPI on Python 3.13, deployed to an Amazon Lightsail container service (nano, one node) in us-east-1. Frames captured at 640×480 JPEG q70 — the same format the eval fixtures are stored in, so the harness sends what the browser sends. Fixture images from Wikimedia Commons, attributed in the repository. Bark sound effects generated with [ElevenLabs](https://elevenlabs.io).*

*[Try it](https://dog-or-not-lite.6wpv8vensby5c.us-east-1.cs.amazonlightsail.com/) · [Source](https://github.com/xbill9/dog-or-not-lite)*
