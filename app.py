import os
import logging
import wave
import json
import zipfile
import requests
from flask import Flask, request, Response, render_template
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from vosk import Model, KaldiRecognizer

# -------------------------------
# Flask setup
# -------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------
# Twilio credentials (for testing only)
# Replace with your real ones or use environment variables on Render
# -------------------------------
TWILIO_SID = "AC4dba388fb958e1b20dfed8c0394f499f"   # Your Twilio SID
TWILIO_AUTH = "79cd6515c80caabfb04da8b96168759a"                # Your Twilio Auth Token
TWILIO_NUMBER = "+15744657235"                      # Your Twilio phone number

client = Client(TWILIO_SID, TWILIO_AUTH)

# -------------------------------
# Keyword categories
# -------------------------------
positive_keywords = ["yes", "interested", "okay", "sure", "yeah"]
negative_keywords = ["no", "not interested", "later", "stop"]

# -------------------------------
# Download & load Vosk model
# -------------------------------
def download_vosk_model():
    if not os.path.exists("models"):
        os.makedirs("models", exist_ok=True)
    model_path = "models/vosk-model-small-en-us-0.15"
    if not os.path.exists(model_path):
        print("🔽 Downloading Vosk model (small-en)...")
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        r = requests.get(url, stream=True)
        with open("models/model.zip", "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print("✅ Extracting model...")
        with zipfile.ZipFile("models/model.zip", "r") as zip_ref:
            zip_ref.extractall("models/")
        os.remove("models/model.zip")
    return model_path

MODEL_PATH = download_vosk_model()
model = Model(MODEL_PATH)

# -------------------------------
# Helper: Transcribe audio with Vosk
# -------------------------------
def transcribe_audio(file_path):
    wf = wave.open(file_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)
    text = ""

    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res = json.loads(rec.Result())
            text += " " + res.get("text", "")
    wf.close()
    return text.strip()

# -------------------------------
# Home page (UI)
# -------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# -------------------------------
# Bulk calling route
# -------------------------------
@app.route("/call", methods=["POST"])
def bulk_call():
    numbers_raw = request.form.get("numbers", "")
    numbers = [n.strip() for n in numbers_raw.split(",") if n.strip()]
    call_results = []

    for num in numbers:
        call = client.calls.create(
            to=num,
            from_=TWILIO_NUMBER,
            url=request.url_root + "voice"
        )
        call_results.append({num: call.sid})

    return {
        "status": "success",
        "message": f"Started {len(numbers)} calls",
        "details": call_results
    }

# -------------------------------
# Voice endpoint (Twilio webhook)
# -------------------------------
@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    resp.play(url=request.url_root + "static/intro.mp3")
    resp.record(
        maxLength="10",
        action=request.url_root + "process_recording",
        playBeep=True
    )
    return Response(str(resp), mimetype="application/xml")

# -------------------------------
# Process recorded voice
# -------------------------------
@app.route("/process_recording", methods=["POST"])
def process_recording():
    recording_url = request.form.get("RecordingUrl")
    caller = request.form.get("To", "unknown")
    logging.info(f"Recording received from {caller}: {recording_url}")

    # Download Twilio recording (.wav)
    audio_path = f"static/{caller.replace('+', '')}.wav"
    r = requests.get(recording_url + ".wav")
    with open(audio_path, "wb") as f:
        f.write(r.content)

    # Transcribe using Vosk
    text = transcribe_audio(audio_path)
    logging.info(f"Transcribed text: {text}")

    # Categorize
    category = "unclear"
    if any(w in text.lower() for w in positive_keywords):
        category = "interested"
    elif any(w in text.lower() for w in negative_keywords):
        category = "not interested"

    # Save response
    with open("responses.txt", "a") as f:
        f.write(f"{caller}: {text} → {category}\n")

    # Respond with message
    resp = VoiceResponse()
    if category == "interested":
        resp.play(url=request.url_root + "static/positive.mp3")
    elif category == "not interested":
        resp.play(url=request.url_root + "static/negative.mp3")
    else:
        resp.say("Thank you for your response.")
    return Response(str(resp), mimetype="application/xml")

# -------------------------------
# View responses
# -------------------------------
@app.route("/responses", methods=["GET"])
def view_responses():
    if not os.path.exists("responses.txt"):
        return "<h2>No responses yet.</h2>"

    with open("responses.txt", "r") as f:
        rows = [line.strip().split(":", 1) for line in f.readlines()]

    html = """
    <h2>📞 Caller Responses</h2>
    <table border="1" cellpadding="8" cellspacing="0">
        <tr><th>Caller</th><th>Response</th></tr>
    """
    for caller, response in rows:
        html += f"<tr><td>{caller}</td><td>{response}</td></tr>"

    html += "</table>"
    return html

# -------------------------------
# Run Flask app
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
