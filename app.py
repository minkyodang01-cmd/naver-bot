from flask import Flask, request
import csv
import requests
import os
import time
import jwt

app = Flask(__name__)

BOT_ID = os.environ["BOT_ID"]
CATEGORY_LIST = ["HKMC", "GM", "RENAULT", "APTIV"]

data = []


def to_int(value, default=0):
    try:
        return int(str(value).strip())
    except:
        return default


with open("data.csv", newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if str(row.get("사용여부", "")).strip().upper() == "Y":
            cleaned = {
                "구분": str(row.get("구분", "")).strip().upper(),
                "페이지": to_int(row.get("페이지", 1), 1),
                "정렬순서": to_int(row.get("정렬순서", 9999), 9999),
                "스펙코드": str(row.get("스펙코드", "")).strip(),
                "간단설명": str(row.get("간단설명", "")).strip(),
                "PDF링크": str(row.get("PDF링크", "")).strip()
            }
            data.append(cleaned)


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


def send_request(user_id, body):
    token = get_token()

    url = f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    r = requests.post(url, headers=headers, json=body, timeout=10)

    print("SEND STATUS:", r.status_code)
    print("SEND RESPONSE:", r.text)

    r.raise_for_status()


def send_text_message(user_id, text):
    body = {
        "content": {
            "type": "text",
            "text": text
        }
    }
    send_request(user_id, body)


def send_category_menu(user_id):
    body = {
        "content": {
            "type": "button_template",
            "contentText": "스펙 구분을 선택하세요.",
            "actions": [
                {"type": "message", "label": "HKMC", "text": "CAT|HKMC"},
                {"type": "message", "label": "GM", "text": "CAT|GM"},
                {"type": "message", "label": "RENAULT", "text": "CAT|RENAULT"},
                {"type": "message", "label": "APTIV", "text": "CAT|APTIV"}
            ]
        }
    }
    send_request(user_id, body)


def get_pages_by_category(category):
    pages = sorted(
        list({row["페이지"] for row in data if row["구분"] == category})
    )
    return pages


def send_page_menu(user_id, category):
    pages = get_pages_by_category(category)

    if not pages:
        send_text_message(user_id, f"{category} 목록이 없습니다.")
        return

    if len(pages) == 1:
        send_list_message(user_id, category, pages[0])
        return

    actions = []
    for page in pages[:10]:
        actions.append({
            "type": "message",
            "label": f"{page}페이지",
            "text": f"PAGE|{category}|{page}"
        })

    body = {
        "content": {
            "type": "button_template",
            "contentText": f"{category} 페이지를 선택하세요.",
            "actions": actions
        }
    }

    send_request(user_id, body)


def send_list_message(user_id, category, page):
    rows = [
        row for row in data
        if row["구분"] == category and row["페이지"] == page
    ]

    rows.sort(key=lambda x: x["정렬순서"])

    if not rows:
        send_text_message(user_id, f"{category} {page}페이지 목록이 없습니다.")
        return

    elements = []
    for row in rows[:4]:
        elements.append({
            "title": row["스펙코드"],
            "subtitle": row["간단설명"],
            "action": {
                "type": "uri",
                "label": "보기",
                "uri": row["PDF링크"]
            }
        })

    body = {
        "content": {
            "type": "list_template",
            "headerText": f"{category} {page}페이지",
            "elements": elements
        }
    }

    send_request(user_id, body)
    send_page_nav(user_id, category, page)


def send_page_nav(user_id, category, current_page):
    pages = get_pages_by_category(category)
    max_page = max(pages) if pages else 1

    actions = []

    if current_page > 1:
        actions.append({
            "type": "message",
            "label": "이전",
            "text": f"PAGE|{category}|{current_page - 1}"
        })

    if current_page < max_page:
        actions.append({
            "type": "message",
            "label": "다음",
            "text": f"PAGE|{category}|{current_page + 1}"
        })

    actions.append({
        "type": "message",
        "label": "처음",
        "text": f"PAGE|{category}|1"
    })

    actions.append({
        "type": "message",
        "label": "구분선택",
        "text": "스펙"
    })

    body = {
        "content": {
            "type": "button_template",
            "contentText": f"{category} {current_page}/{max_page}",
            "actions": actions[:10]
        }
    }

    send_request(user_id, body)


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True)
    print("CALLBACK JSON:", req)

    user_id = req["source"]["userId"]
    msg = str(req["content"]["text"]).strip().upper()

    if msg in ["스펙".upper(), "SPEC"]:
        send_category_menu(user_id)
        return "ok", 200

    if msg.startswith("CAT|"):
        category = msg.split("|", 1)[1].strip().upper()
        if category in CATEGORY_LIST:
            send_page_menu(user_id, category)
        return "ok", 200

    if msg.startswith("PAGE|"):
        parts = msg.split("|")
        if len(parts) == 3:
            category = parts[1].strip().upper()
            page = to_int(parts[2], 1)
            if category in CATEGORY_LIST:
                send_list_message(user_id, category, page)
        return "ok", 200

    if msg in CATEGORY_LIST:
        send_page_menu(user_id, msg)
        return "ok", 200

    return "ok", 200


app.run(host="0.0.0.0", port=10000)
