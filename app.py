import os
import logging
import json
import zipfile
import requests
import wave

from flask import Flask, request, Response, render_template, jsonify
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from vosk import Model, KaldiRecognizer

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------
# HARD-CODED TWILIO CREDENTIALS (FOR TESTING ONLY)
# -------------------------------
TWILIO_SID = "AC4dba388fb958e1b20dfed8c0394f499f"
TWILIO_AUTH = "d0f66a86573bca9f8e878b88c60bc4d9"
TWILIO_NUMBER = "+15744657235"

client = Client(TWILIO_SID, TWILIO_AUTH)

# -------------------------------
# Download Vosk model automatically if not found
# -------------------------------
def download_vosk_model():
    if not os.path.exists("models"):
        os.makedirs("models", exist_ok=True)
    model_path = "models/vosk-model-small-en-us-0.15"
    if not os.path.exists(model_path):
        print("Downloading Vosk model...")
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        r = requests.get(url)
        with open("models/model.zip", "wb") as f:
            f.write(r.content)
        with zipfile.ZipFile("models/model.zip", "r") as zip_ref:
            zip_ref.extractall("models/")
        os.remove("models/model.zip")
    return model_path

MODEL_PATH = download_vosk_model()
vosk_model = Model(MODEL_PATH)

positive_keywords = ["yes", "interested", "okay", "sure", "yeah"]
negative_keywords = ["no", "not interested", "later", "stop"]

# -------------------------------
# Homepage UI
# -------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# -------------------------------
# Bulk Calling Route (fixed JSON)
# -------------------------------
@app.route("/call", methods=["POST"])
def bulk_call():
    numbers_raw = request.form.get("numbers", "")
    numbers = [n.strip() for n in numbers_raw.split(",") if n.strip()]
    call_results = []

    for num in numbers:
        try:
            call = client.calls.create(
                to=num,
                from_=TWILIO_NUMBER,
                url=request.url_root + "voice"
            )
            call_results.append({num: call.sid})
        except Exception as e:
            call_results.append({num: f"Error: {str(e)}"})

    return jsonify({
        "status": "success",
        "message": f"Started {len(numbers)} calls",
        "details": call_results
    })

# -------------------------------
# When call is answered → Play intro + gather speech
# -------------------------------
@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    resp.play(url=request.url_root + "static/intro.mp3")
    resp.gather(
        input="speech",
        action=request.url_root + "gather",
        method="POST",
        timeout=2,
        speechTimeout="auto"
    )
    return Response(str(resp), mimetype="application/xml")

# -------------------------------
# Handle speech response from caller
# -------------------------------
@app.route("/gather", methods=["POST"])
def gather():
    speech = (request.form.get("SpeechResult") or "").lower()
    caller = request.form.get("To", "unknown")
    logging.info(f"Caller {caller} said: {speech}")

    # Save response
    with open("responses.txt", "a") as f:
        f.write(f"{caller}: {speech}\n")

    resp = VoiceResponse()
    if any(w in speech for w in positive_keywords):
        resp.play(url=request.url_root + "static/positive.mp3")
    elif any(w in speech for w in negative_keywords):
        resp.play(url=request.url_root + "static/negative.mp3")
    else:
        resp.say("Sorry, I could not understand you. Please try again later.")

    return Response(str(resp), mimetype="application/xml")

# -------------------------------
# View all responses (summarized)
# -------------------------------
@app.route("/responses", methods=["GET"])
def view_responses():
    if not os.path.exists("responses.txt"):
        return "<h2>No responses yet.</h2>"

    summary = {}
    with open("responses.txt", "r") as f:
        for line in f:
            if ":" not in line:
                continue
            caller, response = line.strip().split(":", 1)
            text = response.lower()
            if any(w in text for w in positive_keywords):
                summary[caller] = "Interested"
            elif any(w in text for w in negative_keywords):
                summary[caller] = "Not Interested"
            else:
                summary[caller] = "Unclear"

    html = """
    <h2>📋 Caller Responses</h2>
    <table border="1" cellpadding="8" cellspacing="0">
        <tr><th>Caller</th><th>Response Category</th></tr>
    """
    for caller, category in summary.items():
        html += f"<tr><td>{caller}</td><td>{category}</td></tr>"

    html += "</table>"
    return html

# -------------------------------
# Run Flask app
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
