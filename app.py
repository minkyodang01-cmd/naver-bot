from flask import Flask, request, jsonify
import csv

app = Flask(__name__)

data = []

with open('data.csv', newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['사용여부'] == 'Y':
            data.append(row)

@app.route("/", methods=["POST"])
def bot():
    req = request.json
    msg = req.get("content", {}).get("text", "").upper()

    if msg == "ES":
        result = "[ES 스펙 목록]\n\n"

        for row in data:
            if row['구분'] == 'ES':
                result += f"{row['스펙코드']} - {row['간단설명']}\n"
                result += f"다운로드: {row['PDF링크']}\n\n"

        return jsonify({
            "content": {
                "type": "text",
                "text": result
            }
        })

    return jsonify({
        "content": {
            "type": "text",
            "text": "ES 또는 SPEC 입력하세요"
        }
    })

app.run(host="0.0.0.0", port=10000)