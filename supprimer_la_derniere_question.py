import json

# Charger les données
with open("questions_responses.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# Supprimer la dernière question
if data:
    last_key = list(data.keys())[-1]
    print(f"Suppression de la dernière question : {last_key}")
    del data[last_key]

    # Réécrire le fichier sans la dernière question
    with open("questions_responses.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
else:
    print("Le fichier est vide.")

"""

aide_vie_etudiante_associations = {
    "UCPH": "aide aux étudiants précaires et sans-abri",
    "UEJF": "aide et soutien aux étudiants",
    "ESSA": "épicerie sociale et solidaire Agorae",
    "LATHENA": "actions solidaires et humanitaires",
    "Antenne Jeunes UNICEF": "actions humanitaires",
    "FAUN": "fédération des associations, défense des intérêts étudiants",
    "UNEF": "syndicat étudiant, défense des droits",
    "UGEN": "défense des intérêts étudiants",
    "Union Étudiante": "représentation et actions de solidarité",
    "PSYCHX": "soutien aux étudiants en psychologie"
}
"""