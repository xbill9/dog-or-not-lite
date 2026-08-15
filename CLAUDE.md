# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

**Dog or Not: Lite** — hold something up to the camera, press SCAN, it tells you
whether it is a dog. FastAPI + Amazon Bedrock (Nova Lite), deployed as a single
Amazon Lightsail container service. Built for the AWS Weekend Creative
Challenge (deadline 2026-08-17 13:00 PT).

A deliberate reduction of the sibling project `~/devto-dog` (live Gemini
streaming over WebSockets, ~3,000 lines of client code). Do not port features
back in from there — "less complicated" is the design, not an accident.

## Commands

- `MOCK=1 ./run.sh` — offline, no credentials, no bill. **Use this for all UI
  work.** Cycles four canned verdicts, which is the only way to reach the
  NOT A DOG and FELINE INTRUSION states on demand.
- `./run.sh` — real Bedrock calls against `us.amazon.nova-lite-v1:0`.
- `./check.py [--url URL] [--min-rate 0.9]` — score 20 fixtures. Stdlib only, so
  it runs against a deployed URL from anywhere.
- `./iam-setup.sh` — create/refresh the scoped IAM user. Mints a **new** access
  key every run and deletes the old ones.
- `./deploy.sh` — build, push, deploy. Idempotent; same service, same URL.

There is no test suite and no linter config. `check.py` is the only thing that
measures anything.

## Deploying

Order matters, and steps 1–2 are one-time:

1. `aws login` — the account root is what this was set up with.
2. `./iam-setup.sh` — writes `~/dogornot-lite.key` (chmod 600, outside the repo).
3. `./deploy.sh` — takes roughly 5–10 minutes on a first deploy, most of it
   Lightsail provisioning the service before it will accept a deployment.
4. `./check.py --url <live url>` — the only real verification. `/healthz`
   passing proves the container booted, not that Bedrock is reachable from it.

Service: `dog-or-not-lite`, `nano` power, scale 1, `us-east-1`.

### Tearing it down

A Lightsail container service bills while it exists, whether or not anyone uses
it — roughly $7/month at `nano`. Deleting the deployment does not stop it; you
must delete the service:

```bash
aws lightsail delete-container-service --service-name dog-or-not-lite
aws iam delete-user-policy --user-name dog-or-not-lite --policy-name InvokeNovaLite
aws iam list-access-keys --user-name dog-or-not-lite   # delete each, then:
aws iam delete-user --user-name dog-or-not-lite
```

## Gotchas

- **Lightsail container services have no IAM task role.** Unlike ECS or Lambda
  there is nothing to attach a policy to, so the container needs a real access
  key as an environment variable. That is the genuine security cost of choosing
  Lightsail. The mitigation is scope, not secrecy: `iam-setup.sh` creates a user
  that can call `InvokeModel` on one model family and nothing else. Deployment
  environment variables are readable afterwards via
  `get-container-services`, so never put anything broader in there.

- **A cross-region inference profile needs wildcard-region IAM. Measured.**
  `us.amazon.nova-lite-v1:0` routes across regions, and Bedrock checks
  `InvokeModel` against the underlying foundation-model ARN in *each* one. With
  the policy pinned to `us-east-1`, a call made **to** `us-east-1` fails with:

  ```
  AccessDeniedException: ... not authorized to perform: bedrock:InvokeModel on
  resource: arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0
  ```

  `us-west-2` — never requested, never configured. The policy needs the
  inference-profile ARN *and* `arn:aws:bedrock:*::foundation-model/...`. This
  was verified by narrowing the policy on purpose and restoring it, not
  inferred from docs.

- **`--platform linux/amd64` is not optional** in `deploy.sh`. Lightsail nodes
  are x86; an arm64 image builds, pushes and deploys cleanly and then
  crash-loops with an exec format error that never mentions architecture.

- **`aws login` credentials need `botocore[crt]`, which is deliberately NOT in
  `requirements.txt`.** Locally, boto3 hits
  `Missing Dependency: Using the login credential provider requires ... botocore[crt]`
  and the app returns `502 bedrock unreachable`. It is installed in `.venv`
  only. The container authenticates with a static key pair, which needs no CRT,
  and adding it would put ~20 MB in the image for nothing.

- **`lightsailctl` is required by `aws lightsail push-container-image`** and is a
  separate binary. On this machine it is already at `~/.local/bin/lightsailctl`;
  checking only `/usr/local/bin` will wrongly report it missing. Check
  `command -v lightsailctl`.

- **`StaticFiles` is mounted last in `app.py`, and must stay last.** Mounting at
  `/` before the routes would shadow `/api/scan`, `/api/config` and `/healthz`.

- **The boto3 client is built lazily.** Constructing it at import fails on a
  machine with no credentials, which would break `MOCK=1` — the mode whose whole
  point is needing none.

- **Do not put a CSS `transition` on the verdict colours.** `.meter i` had
  `transition: background 0.3s` and the bar showed the *previous* verdict's
  colour indefinitely — green under NOT A DOG, red under FELINE INTRUSION —
  while the verdict text, which has no transition, switched correctly. Width is
  the only thing worth animating. Reproduced by setting each state with a 700 ms
  settle and reading `getComputedStyle`.

- **`pkill -f "app.py"` kills its own shell**, because the pattern matches the
  bash command line running it (exit 144, no explanation). Use
  `fuser -k -n tcp 8080`.

- **The pushed image reference is read back from `get-container-images`**, not
  scraped from the push output, which prints it in prose. The version number is
  not sequential from 1 — a brand-new service's first image came back as
  `:dog-or-not-lite.scanner.219`. That is normal; do not go looking for 218
  earlier images.

- **Fixtures are stored at 640×480 q70 — the exact format the browser sends.**
  Not pristine originals the app will never see. Expectations in
  `fixtures/fixtures.json` were verified by eye before being committed:
  generate the input, never the expectation.

- **20/20 on the fixtures is a smoke test, not a benchmark.** Measured locally
  at median 831 ms per scan. The images are clean, well-lit and
  subject-fills-frame; it says the prompt works, not that the rule is robust.

- **`toolChoice` forces the verdict.** Without it Nova will sometimes narrate
  instead of calling the tool, and the failure lands exactly on the ambiguous
  images where a parser is least reliable.

- **Secrets never reach a command line.** `deploy.sh` builds the container JSON
  with python and passes it via `file://` from a `chmod 700` tempdir, so the key
  never appears in `ps`. `.dockerignore` and `.gitignore` both exclude `*.key`
  and `.env`.

## Style

Vanilla everything: no framework, no build step, no bundler, no TypeScript, no
Tailwind. Three static files. Keep it that way — the reduction *is* the point,
and the sibling project exists for anyone who wants the elaborate version.
