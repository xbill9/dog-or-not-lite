/*
 * Dog or Not: Lite -- the whole client.
 *
 * Press a button, one frame goes to the server, one verdict comes back. There
 * is no socket, no stream and no session; the full build has all three and this
 * is the version that fits in one file.
 */

const $ = (id) => document.getElementById(id);

const el = {
    video: $('video'),
    still: $('still'),
    canvas: $('canvas'),
    placeholder: $('placeholder'),
    busy: $('busy'),
    readout: $('readout'),
    verdict: $('verdict'),
    subject: $('subject'),
    confidence: $('confidence'),
    elapsed: $('elapsed'),
    meterFill: $('meterFill'),
    note: $('note'),
    camera: $('camera'),
    scan: $('scan'),
    file: $('file'),
    model: $('model'),
};

// 640x480 q70 is what the full build measured as the point where shrinking
// starts costing real accuracy -- a hand (or a dog) at arm's length loses its
// detail first, and the saving is not worth it.
const CAPTURE_W = 640;
const CAPTURE_H = 480;
const JPEG_QUALITY = 0.7;

let stream = null;
let busy = false;

/* ---- audio -------------------------------------------------------------- */

// One AudioContext for the page, built on first use. Never in a constructor
// that runs per render: Chrome caps concurrent contexts at about six and then
// refuses to make more, which presents as audio silently failing later.
let ctx = null;
let pack = null;

function audio() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    ctx ??= new Ctx();
    return ctx;
}

async function loadPack(ac) {
    if (pack) return pack;
    try {
        const manifest = await fetch('/audio/barks.json');
        if (!manifest.ok) throw new Error(`barks.json ${manifest.status}`);
        const { clips } = await manifest.json();
        pack = await Promise.all(
            clips.map(async (url) => {
                const r = await fetch(url);
                if (!r.ok) throw new Error(`${url} ${r.status}`);
                return ac.decodeAudioData(await r.arrayBuffer());
            }),
        );
    } catch (e) {
        // A missing pack is a quieter app, never a broken one.
        console.warn('[bark] no audio pack:', e.message);
        pack = [];
    }
    return pack;
}

async function bark() {
    const ac = audio();
    if (!ac) return;
    if (ac.state === 'suspended') await ac.resume();
    const clips = await loadPack(ac);
    if (!clips.length) return;
    const src = ac.createBufferSource();
    src.buffer = clips[Math.floor(Math.random() * clips.length)];
    const gain = ac.createGain();
    gain.gain.value = 0.85;
    src.connect(gain).connect(ac.destination);
    src.start();
}

/**
 * Two-tone klaxon for the feline easter egg. Synthesised rather than sampled,
 * which is why it is the part that always works.
 */
async function alarm() {
    const ac = audio();
    if (!ac) return;
    if (ac.state === 'suspended') await ac.resume();

    const now = ac.currentTime;
    const TONES = [620, 440];
    const BEAT = 0.4;

    for (let i = 0; i < 4; i++) {
        const at = now + i * BEAT;
        const osc = ac.createOscillator();
        osc.type = 'square';
        osc.frequency.value = TONES[i % 2];

        // A raw square wave clips on laptop speakers; the lowpass takes the top
        // off without softening the attack, which is the part that reads as
        // "alarm".
        const lp = ac.createBiquadFilter();
        lp.type = 'lowpass';
        lp.frequency.value = 1800;

        const gain = ac.createGain();
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.2, at + 0.02);
        gain.gain.setValueAtTime(0.2, at + BEAT - 0.06);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + BEAT - 0.01);

        osc.connect(lp).connect(gain).connect(ac.destination);
        osc.start(at);
        osc.stop(at + BEAT);
    }
}

/* ---- camera ------------------------------------------------------------- */

async function startCamera() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: CAPTURE_W }, height: { ideal: CAPTURE_H }, facingMode: 'environment' },
            audio: false, // the microphone has no job here
        });
    } catch (e) {
        setState('error', 'CAMERA REFUSED', {
            note: `${e.name}. Upload an image instead -- it takes the same path.`,
        });
        return;
    }
    el.video.srcObject = stream;
    el.video.hidden = false;
    el.still.hidden = true;
    el.placeholder.hidden = true;
    el.camera.textContent = 'STOP CAMERA';
    el.scan.disabled = false;
    setState('idle', 'AWAITING SUBJECT', { note: 'Hold a subject up and press SCAN.' });
}

function stopCamera() {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    el.video.srcObject = null;
    el.video.hidden = true;
    el.camera.textContent = 'START CAMERA';
    if (el.still.hidden) {
        el.placeholder.hidden = false;
        el.scan.disabled = true;
    }
}

/* ---- capture ------------------------------------------------------------ */

/** The live video frame as a base64 JPEG, and as a data URL to show. */
function grabFrame() {
    const c = el.canvas;
    c.width = CAPTURE_W;
    c.height = CAPTURE_H;
    const g = c.getContext('2d');

    // Letterbox rather than stretch: the model should see the subject in its
    // real proportions, not a squashed one.
    const vw = el.video.videoWidth || CAPTURE_W;
    const vh = el.video.videoHeight || CAPTURE_H;
    const scale = Math.min(CAPTURE_W / vw, CAPTURE_H / vh);
    const w = vw * scale;
    const h = vh * scale;
    g.fillStyle = '#000';
    g.fillRect(0, 0, CAPTURE_W, CAPTURE_H);
    g.drawImage(el.video, (CAPTURE_W - w) / 2, (CAPTURE_H - h) / 2, w, h);

    return c.toDataURL('image/jpeg', JPEG_QUALITY);
}

/** An uploaded file, downscaled through the same canvas so the server sees
 *  one format and one size no matter which button was pressed. */
function readFile(file) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.onload = () => {
            URL.revokeObjectURL(url);
            const c = el.canvas;
            c.width = CAPTURE_W;
            c.height = CAPTURE_H;
            const g = c.getContext('2d');
            const scale = Math.min(CAPTURE_W / img.width, CAPTURE_H / img.height);
            const w = img.width * scale;
            const h = img.height * scale;
            g.fillStyle = '#000';
            g.fillRect(0, 0, CAPTURE_W, CAPTURE_H);
            g.drawImage(img, (CAPTURE_W - w) / 2, (CAPTURE_H - h) / 2, w, h);
            resolve(c.toDataURL('image/jpeg', JPEG_QUALITY));
        };
        img.onerror = () => {
            URL.revokeObjectURL(url);
            reject(new Error('could not decode that file'));
        };
        img.src = url;
    });
}

/* ---- readout ------------------------------------------------------------ */

function setState(state, verdict, { subject, confidence, elapsed, note } = {}) {
    el.readout.dataset.state = state;
    el.verdict.textContent = verdict;
    el.subject.textContent = subject ?? '--';
    el.confidence.textContent = confidence == null ? '--' : `${confidence}%`;
    el.elapsed.textContent = elapsed == null ? '--' : `${elapsed} ms`;
    el.meterFill.style.width = confidence == null ? '0%' : `${confidence}%`;
    if (note) el.note.textContent = note;
}

/* ---- the scan ----------------------------------------------------------- */

async function send(dataUrl) {
    if (busy) return;
    busy = true;
    el.scan.disabled = true;
    el.busy.hidden = false;

    // Show the exact frame the model is judging. If it looks bad here, that is
    // why the verdict is bad -- the single most useful thing this screen does.
    el.still.src = dataUrl;
    el.still.hidden = false;
    el.video.hidden = true;
    el.placeholder.hidden = true;

    const started = performance.now();
    try {
        const res = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl }),
        });
        const elapsed = Math.round(performance.now() - started);

        if (!res.ok) {
            const detail = await res.json().catch(() => ({}));
            setState('error', 'SCANNER FAULT', {
                elapsed,
                note: detail.detail ? `${res.status}: ${detail.detail}` : `HTTP ${res.status}`,
            });
            return;
        }

        const v = await res.json();
        const subject = (v.subject || 'unknown').toUpperCase();

        if (v.is_cat) {
            setState('cat', 'FELINE INTRUSION', {
                subject,
                confidence: v.confidence,
                elapsed,
                note: 'Scanner integrity lost. This unit is not rated for cats.',
            });
            alarm();
        } else if (v.is_dog) {
            setState('dog', 'DOG', {
                subject,
                confidence: v.confidence,
                elapsed,
                note: 'Subject confirmed canine.',
            });
            bark();
        } else {
            setState('notdog', 'NOT A DOG', {
                subject,
                confidence: v.confidence,
                elapsed,
                note: 'Negative. A wolf, a plush, a statue and a drawing are all not a dog.',
            });
        }
    } catch (e) {
        setState('error', 'NO LINK', { note: e.message });
    } finally {
        busy = false;
        el.busy.hidden = true;
        // Re-armed whenever there is something to scan: a live camera, or the
        // still already on screen.
        el.scan.disabled = !stream && el.still.hidden;
    }
}

/* ---- wiring ------------------------------------------------------------- */

el.camera.addEventListener('click', () => (stream ? stopCamera() : startCamera()));

el.scan.addEventListener('click', () => {
    if (!stream) return; // an uploaded still scans on upload, not on SCAN
    send(grabFrame());
});

el.file.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Clearing the value means picking the same file twice still fires change.
    e.target.value = '';
    try {
        const dataUrl = await readFile(file);
        stopCamera();
        await send(dataUrl);
    } catch (err) {
        setState('error', 'UNREADABLE', { note: err.message });
    }
});

// Name the model on screen, from the server rather than a constant here -- a
// hardcoded copy is one that can quietly go stale.
fetch('/api/config')
    .then((r) => r.json())
    .then(({ model }) => {
        el.model.textContent = model;
    })
    .catch(() => {
        el.model.textContent = 'MODEL UNKNOWN';
    });
