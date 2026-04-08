from flask import Flask, request
import csv
import requests
import os
import time
import jwt

app = Flask(__name__)

BOT_ID = os.environ["BOT_ID"]

data = []

with open("data.csv", newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row["사용여부"] == "Y":
            data.append(row)


def get_token():
    now = int(time.time())

    payload = {
        "iss": os.environ["CLIENT_ID"],
        "sub": os.environ["CLIENT_EMAIL"],
        "iat": now,
        "exp": now + 3600
    }

    private_key = os.environ["PRIVATE_KEY"].replace("\\n", "\n")
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    url = "https://auth.worksmobile.com/oauth2/v2.0/token"

    token_data = {
        "assertion": jwt_token,
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "client_id": os.environ["CLIENT_ID"],
        "client_secret": os.environ["CLIENT_SECRET"],
        "scope": "bot.message"
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    r = requests.post(url, data=token_data, headers=headers, timeout=10)

    print("TOKEN STATUS:", r.status_code)
    print("TOKEN RESPONSE:", r.text)

    r.raise_for_status()
    token_json = r.json()

    if "access_token" not in token_json:
        raise Exception(f"access_token 없음: {token_json}")

    return token_json["access_token"]


def send_text_message(user_id, text):
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

    r = requests.post(url, headers=headers, json=body, timeout=10)

    print("TEXT STATUS:", r.status_code)
    print("TEXT RESPONSE:", r.text)

    r.raise_for_status()


def send_spec_menu(user_id):
    token = get_token()

    url = f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "content": {
            "type": "button_template",
            "contentText": "스펙 구분을 선택하세요.",
            "actions": [
                {
                    "type": "message",
                    "label": "ES",
                    "text": "ES"
                },
                {
                    "type": "message",
                    "label": "GM",
                    "text": "GM"
                },
                {
                    "type": "message",
                    "label": "MS",
                    "text": "MS"
                },
                {
                    "type": "message",
                    "label": "RENAULT",
                    "text": "RENAULT"
                },
                {
                    "type": "message",
                    "label": "APTIV",
                    "text": "APTIV"
                }
            ]
        }
    }

    r = requests.post(url, headers=headers, json=body, timeout=10)

    print("MENU STATUS:", r.status_code)
    print("MENU RESPONSE:", r.text)

    r.raise_for_status()


def send_list_message(user_id, category):
    token = get_token()

    url = f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    elements = []

    for row in data:
        if row["구분"].strip().upper() == category:
            elements.append({
                "title": row["스펙코드"],
                "subtitle": row["간단설명"],
                "buttons": [
                    {
                        "type": "uri",
                        "label": "보기",
                        "uri": row["PDF링크"]
                    }
                ]
            })

    if not elements:
        send_text_message(user_id, f"{category} 목록이 없습니다.")
        return

    body = {
        "content": {
            "type": "template",
            "template": {
                "type": "list",
                "cover": {
                    "title": f"{category} 스펙 목록",
                    "data": {
                        "backgroundColor": "#03A9F4"
                    }
                },
                "elements": elements[:10]
            }
        }
    }

    r = requests.post(url, headers=headers, json=body, timeout=10)

    print("LIST STATUS:", r.status_code)
    print("LIST RESPONSE:", r.text)

    r.raise_for_status()


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True)

    print("CALLBACK JSON:", req)

    user_id = req["source"]["userId"]
    msg = req["content"]["text"].strip().upper()

    if msg == "스펙".upper():
    send_spec_menu(user_id)
    return "ok", 200

    if msg in ["ES", "GM", "MS", "RENAULT", "APTIV"]:
        send_list_message(user_id, msg)
        return "ok", 200

    return "ok", 200


app.run(host="0.0.0.0", port=10000)
