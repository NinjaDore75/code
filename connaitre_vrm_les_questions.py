
import json

with open("questions_responses.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("Questions enregistrées :")
for i, question in enumerate(data.keys(), 1):
    print(f"{i}. {question}")


