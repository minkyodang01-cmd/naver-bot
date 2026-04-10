# ▼▼▼ 기존 코드 그대로 유지 + 아래만 추가 ▼▼▼

# =========================
# PRODUCT / OEM CSV 로드 추가
# =========================

PRODUCT_PATH = os.path.join(BASE_DIR, "PRODUCT.csv")
OEM_PATH = os.path.join(BASE_DIR, "OEM.csv")

product_data = []
oem_data = []

try:
    with open(PRODUCT_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if safe_str(row.get("제품명")):
                product_data.append(row)
except:
    print("PRODUCT.csv 로드 실패")

try:
    with open(OEM_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if safe_str(row.get("OEM")):
                oem_data.append(row)
except:
    print("OEM.csv 로드 실패")


# =========================
# PRODUCT 기능
# =========================

def send_product_menu(user_id):
    actions = []

    for row in product_data:
        name = safe_str(row.get("제품명"))
        if name:
            actions.append({
                "type": "message",
                "label": name,
                "text": f"PROD|{name}"
            })

    if not actions:
        send_text_message(user_id, "제품 데이터가 없습니다.")
        return

    body = {
        "content": {
            "type": "button_template",
            "contentText": "제품을 선택하세요",
            "actions": actions[:5]
        }
    }
    send_request(user_id, body)


def send_product_flex(user_id, row):
    name = safe_str(row.get("제품명"))
    desc = safe_str(row.get("설명"))
    img = safe_str(row.get("이미지"))

    if not is_valid_uri(img):
        send_text_message(user_id, f"{name}\n{desc}")
        return

    body = {
        "content": {
            "type": "flex",
            "altText": name,
            "contents": {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": img,
                    "size": "full"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": name, "weight": "bold"},
                        {"type": "text", "text": desc, "wrap": True}
                    ]
                }
            }
        }
    }
    send_request(user_id, body)


# =========================
# OEM 기능
# =========================

def send_oem_flex(user_id):
    bubbles = []

    for row in oem_data:
        name = safe_str(row.get("OEM"))
        img = safe_str(row.get("이미지"))
        pdf = safe_str(row.get("PDF"))

        bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": name, "weight": "bold"}
                ]
            }
        }

        if is_valid_uri(img):
            bubble["hero"] = {
                "type": "image",
                "url": img,
                "size": "full"
            }

        if is_valid_uri(pdf):
            bubble["footer"] = {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "다운로드",
                        "uri": pdf
                    }
                }]
            }

        bubbles.append(bubble)

    if not bubbles:
        send_text_message(user_id, "OEM 데이터가 없습니다.")
        return

    body = {
        "content": {
            "type": "flex",
            "altText": "OEM 목록",
            "contents": {
                "type": "carousel",
                "contents": bubbles[:10]
            }
        }
    }

    send_request(user_id, body)


# =========================
# handle_message에 추가만
# =========================

def handle_message(user_id, raw_msg):
    raw_msg = safe_str(raw_msg)
    msg_normalized = normalize_text(raw_msg)
    msg_upper = raw_msg.upper()

    # FAQ
    if msg_normalized in FAQ_NORMALIZED:
        send_text_message(user_id, FAQ_NORMALIZED[msg_normalized])
        return

    similar_key = find_similar_faq_key(msg_normalized)
    if similar_key:
        send_text_message(user_id, FAQ_NORMALIZED[similar_key])
        return

    # ------------------
    # PRODUCT 추가
    # ------------------
    if msg_normalized == "제품":
        send_product_menu(user_id)
        return

    if msg_upper.startswith("PROD|"):
        name = msg_upper.split("|")[1]

        for row in product_data:
            if normalize_text(row.get("제품명")) == normalize_text(name):
                send_product_flex(user_id, row)
                return

    # ------------------
    # OEM 추가
    # ------------------
    if msg_normalized == "OEM":
        send_oem_flex(user_id)
        return

    # ------------------
    # 기존 스펙 그대로
    # ------------------
    if msg_normalized in ["스펙", "스팩", "SPEC"]:
        send_category_menu(user_id)
        return

    if msg_upper.startswith("CAT|"):
        category = msg_upper.split("|", 1)[1].strip().upper()
        if category in CATEGORY_LIST:
            send_flex_spec_pages(user_id, category)
            return

    if msg_upper in CATEGORY_LIST:
        send_flex_spec_pages(user_id, msg_upper)
        return

    send_text_message(user_id, "원하시는 기능을 찾지 못했습니다.")
