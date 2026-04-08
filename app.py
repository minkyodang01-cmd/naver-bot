from flask import Flask, request
import csv
import json
import requests

app = Flask(__name__)

BOT_ID = "11904007"
CLIENT_ID = "k8BuMV8YBuFoEaM0fRGt"
CLIENT_SECRET = "TXTRq46lYq"

data = []

with open('data.csv', newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['사용여부'] == 'Y':
            data.append(row)

def get_token():
    url = "https://auth.worksmobile.com/oauth2/v2.0/token"

    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "bot.message"
    }

    r = requests.post(url, data=payload)
    return r.json()["access_token"]

def send_message(user_id, text):
    token = get_token()

    url = f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "content": {
            "type": "text",
            "text": text
        }
    }

    requests.post(url, headers=headers, json=body)

@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True)

    user_id = req["source"]["userId"]
    msg = req["content"]["text"].strip().upper()

    if msg == "ES":
        result = "[ES 스펙 목록]\n\n"
        for row in data:
            if row['구분'] == 'ES':
                result += f"{row['스펙코드']} - {row['간단설명']}\n"
                result += f"{row['PDF링크']}\n\n"

        send_message(user_id, result)

    return "ok", 200

app.run(host="0.0.0.0", port=10000)
