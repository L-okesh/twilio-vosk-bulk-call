import os
import logging
import requests
import wave
import json
import zipfile
from flask import Flask, request, Response, render_template
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from vosk import Model, KaldiRecognizer
from huggingface_hub import hf_hub_download

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------------------------------
# HARD-CODED TWILIO CREDENTIALS (TEST PURPOSES ONLY)
# ------------------------------------------
TWILIO_SID = "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # ← Your Twilio SID
TWILIO_AUTH = "your_auth_token_here"               # ← Your Twilio Auth Token
TWILIO_NUMBER = "+1XXXXXXXXXX"                     # ← Your Twilio Number
client = Client(TWILIO_SID, TWILIO_AUTH)

# ------------------------------------------
# Keywords / Categories
# ------------------------------------------
positive_keywords = ["yes", "interested", "okay", "sure", "yeah"]
negative_keywords = ["no", "not interested", "stop"]
later_keywords = ["later", "call later"]

# ------------------------------------------
# Vosk model download from Hugging Face
# ------------------------------------------
MODEL_DIR = "models/vosk-small-en"
if not os.path.exists(MODEL_DIR):
    print("Downloading Vosk model from Hugging Face...")
    archive_path = hf_hub_download(
        repo_id="alphacep/vosk-model-small-en-us-0.15",
        filename="model.zip",
        repo_type="model"
    )
    with zipfile.ZipFile(archive_path, "r") as zip_ref:
        zip_ref.extractall("models")
    print("Vosk model ready!")

model = Model(MODEL_DIR)

# ------------------------------------------
# Homepage
# ------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# ------------------------------------------
# Bulk calling
# ------------------------------------------
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

# ------------------------------------------
# When call is answered → play intro + record speech
# ------------------------------------------
@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    resp.play(url=request.url_root + "static/intro.mp3")
    resp.record(
        action=request.url_root + "gather",
        method="POST",
        maxLength=10,
        playBeep=True,
        timeout=3
    )
    return Response(str(resp), mimetype="application/xml")

# ------------------------------------------
# Gather recorded audio & classify response
# ------------------------------------------
@app.route("/gather", methods=["POST"])
def gather():
    recording_url = request.form.get("RecordingUrl")
    caller = request.form.get("To", "unknown")

    # Download Twilio recording
    audio_file = f"temp_{caller}.wav"
    r = requests.get(recording_url)
    with open(audio_file, "wb") as f:
        f.write(r.content)

    # Transcribe using Vosk
    wf = wave.open(audio_file, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    text = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text += " " + result.get("text", "")
    text += " " + json.loads(rec.FinalResult()).get("text", "")
    text = text.lower().strip()
    os.remove(audio_file)  # remove temp file

    # Classify response
    if any(w in text for w in positive_keywords):
        response_category = "Interested"
        resp_play = request.url_root + "static/positive.mp3"
    elif any(w in text for w in negative_keywords):
        response_category = "Not Interested"
        resp_play = request.url_root + "static/negative.mp3"
    elif any(w in text for w in later_keywords):
        response_category = "Later"
        resp_play = request.url_root + "static/later.mp3"
    else:
        response_category = "Unknown"
        resp_play = None

    # Save response
    with open("responses.txt", "a") as f:
        f.write(f"{caller}:{response_category}\n")

    # Respond to caller
    resp = VoiceResponse()
    if resp_play:
        resp.play(url=resp_play)
    else:
        resp.say("Sorry, I could not understand you. Please try again later.")
    return Response(str(resp), mimetype="application/xml")

# ------------------------------------------
# View responses
# ------------------------------------------
@app.route("/responses", methods=["GET"])
def view_responses():
    if not os.path.exists("responses.txt"):
        return "<h2>No responses yet.</h2>"

    with open("responses.txt", "r") as f:
        rows = [line.strip().split(":", 1) for line in f.readlines()]

    html = """
    <h2>Caller Responses</h2>
    <table border="1" cellpadding="8" cellspacing="0">
        <tr><th>Caller</th><th>Response</th></tr>
    """
    for caller, response in rows:
        html += f"<tr><td>{caller}</td><td>{response}</td></tr>"

    html += "</table>"
    return html

# ------------------------------------------
# Run server
# ------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
