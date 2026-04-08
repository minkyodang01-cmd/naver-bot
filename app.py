from flask import Flask, request
import csv
import json

app = Flask(__name__)

data = []

with open('data.csv', newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['사용여부'] == 'Y':
            data.append(row)

@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True, silent=True)

    print("=== CALLBACK JSON START ===")
    print(json.dumps(req, ensure_ascii=False))
    print("=== CALLBACK JSON END ===")

    return "ok", 200

app.run(host="0.0.0.0", port=10000)
