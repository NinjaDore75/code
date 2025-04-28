import json
import re
import aiohttp
import asyncio
import ollama
from fuzzywuzzy import fuzz
import os
from bs4 import BeautifulSoup
import random
import time

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}


def load_data_from_file(filename="questions_responses.json"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_data_to_file(data, filename="questions_responses.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_cached_data(filename="cached_pages.json"):
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
                now = time.time()
                filtered_data = {}
                for url, info in data.items():
                    if isinstance(info, dict):
                        timestamp = info.get("timestamp", now)
                        content = info.get("content", info)
                    else:
                        timestamp = now
                        content = info

                    if now - timestamp < 7 * 24 * 3600:
                        filtered_data[url] = content

                return filtered_data
        except json.JSONDecodeError:
            print(f"Error decoding {filename}. Starting with an empty cache.")
            return {}
    return {}


def save_cached_data(data, filename="cached_pages.json"):
    cache_with_timestamps = {}
    for url, content in data.items():
        cache_with_timestamps[url] = {
            "content": content,
            "timestamp": time.time()
        }
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cache_with_timestamps, f, ensure_ascii=False, indent=4)


def extract_phone_number(text):
    # Version améliorée pour capter plus de formats de téléphone
    phone_regex = r"(?:(?:(?:\+|00)33[ ]?(?:\(0\)[ ]?)?)|0)[ ]?[1-9](?:[ .-]?\d{2}){4}"
    matches = re.findall(phone_regex, text)
    if matches:
        return matches[0]

    # Format secondaire, plus général
    basic_regex = r"(?:0\d[ .-]?\d{2}[ .-]?\d{2}[ .-]?\d{2}[ .-]?\d{2})"
    basic_matches = re.findall(basic_regex, text)
    if basic_matches:
        return basic_matches[0]

    return None


def extract_email(text):
    email_regex = r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
    match = re.search(email_regex, text)
    if match:
        return match.group(0)
    return None


def get_contact_info_from_text(text, is_association_question=False):
    phone_number = extract_phone_number(text)
    email = extract_email(text)

    contact_info = None
    if phone_number or email:
        contact_info = "Informations de contact : "
        if phone_number:
            contact_info += f"Téléphone : {phone_number} "
        if email:
            contact_info += f"Email : {email}"
    return contact_info  # Retourner l'information au lieu de None


batiments_universite = {
    "Remond": {"lettre": "A", "ufr": "UFR de Science Politique", "localisation": "ouest, nord ouest"},
    "Grappin": {"lettre": "B", "ufr": "UFR de Philosophie", "localisation": "ouest"},
    "Zazzo": {"lettre": "C", "ufr": "UFR de Psychologie", "localisation": "ouest"},
    "Lefebvre": {"lettre": "D", "ufr": "UFR de Sociologie", "localisation": "ouest",
                 "ufr": "Sciences Sociales et Administration"},
    "Ramnoux": {"lettre": "E", "ufr": "UFR de Littérature Comparée", "localisation": "ouest"},
    "Veil": {"lettre": "F", "localisation": "sud", "ufr": "Droit et Science Politique"},  # UFR non précisée
    "Allais": {"lettre": "G", "localisation": "sud",
               "ufr": "Sciences Economiques Gestion Mathématiques et Informatiques"},  # UFR non précisée
    "Omnisport": {"lettre": "H", "localisation": "sud"},  # Centre sportif
    "Éphémère 1": {"lettre": "M",
                   "ufr": "Direction des affaires logistique et optimisation des environnements du travail",
                   "localisation": "sud"},  # Temporaire, sans UFR précise
    "Maison de l'Étudiant": {"lettre": "MDE", "localisation": "centre, sud ouest"},
    "Ricoeur": {"lettre": "L", "localisation": "est",
                "ufr": "Philosophie Information-Communication Langage Littérature Arts du Spectacle"},
    # UFR non précisée
    "Gymnase": {"lettre": "I"},  # Sport
    "Maier": {"lettre": "V", "localisation": "nord", "ufr": "Langues et Cultures Etrangères"},  # UFR non précisée
    "Milliat": {"lettre": "S", "ufr": "Sciences Techniques des Activités Physiques et sportives",
                "localisation": "Nord"},  # UFR non précisée
    "Éphémère 2": {"lettre": "N", "localisation": "nord"},  # Temporaire
    "BU": {"lettre": "BU", "localisation": "est"},  # Bibliothèque universitaire
    "Restaurant Universitaire": {"lettre": "RU", "localisation": " ouest"},  # Resto U
    "Delbo": {"lettre": "BSL", "ufr": "UFR Lettres, Langues, Arts", "localisation": "sud"},
    "Ginouvès (MAE)": {"lettre": "MAE", "ufr": "Maison Archéologie & Ethnologie"},  # Maison Archéologie & Ethnologie
    "Weber": {"lettre": "W", "localisation": "nord", "ufr": "Salle d'Amphithéâtre"},  # Bâtiment inter-UFR
    "Rouch": {"lettre": "DD"},  # Double lettre, UFR non précisée
    "Formation Continue": {"lettre": "FC", "localisation": "sud"},  # Pour adultes/pros
    "Centre Sportif": {"lettre": "CS", "localisation": "centre"}  # Centre sport global
}


def extract_keywords(question):
    stopwords = {"le", "la", "les", "un", "une", "des", "et", "ou", "de", "du", "au", "aux", "a", "à", "est", "sont",
                 "pour", "dans", "par", "avec", "ce", "cette", "ces", "il", "elle", "ils", "elles", "je", "tu", "nous",
                 "vous"}

    words = re.findall(r'\b\w+\b', question.lower())
    keywords = [word for word in words if word not in stopwords and len(word) > 2]
    question_lower = question.lower()
    if ("téléphone" in question or "phone" in question or "contact" in question
            or "mail" in question or "email" in question or "courriel" in question):
        keywords.append("contact")
        if "téléphone" in question or "phone" in question:
            keywords.append("telephone")
        if "mail" in question or "email" in question or "courriel" in question:
            keywords.append("email")

    if "handicap" in question or "accessibilité" in question or "handicapé" in question:
        keywords.extend(["handicap", "accessibilite", "sha"])
    if "crous" in question or "resto" in question or "restaurant" in question:
        keywords.append("crous")
    if ("transport" in question or "bus" in question or "metro" in question
            or "rer" in question or "train" in question or "imagine" in question):
        keywords.extend(["transport", "imagine-r"])
    if "sport" in question or "suaps" in question or "activité physique" in question:
        keywords.extend(["sport", "suaps", "activite", "physique"])
    if "art martial" in question or "arts martiaux" in question or "judo" in question or "karate" in question or "kung fu" in question:
        keywords.extend(["art martial", "combat", "judo", "karate", "boxe", "self-defense"])
    if "association" in question or "club" in question or "étudiant" in question or "asso" in question:
        keywords.extend(["association", "club", "etudiant", "aca2"])
        is_association_question = True
        is_crous_question = False  # Explicitly override

    if "bâtiment" in question_lower or "batiment" in question_lower or "bât" in question_lower:
        keywords.append("batiment")
        for batiment in batiments_universite.keys():
            if batiment.lower() in question_lower:
                keywords.append(batiment.lower())

    if "ufr" in question_lower:
        keywords.append("ufr")
        # Détection des UFR spécifiques
        for batiment, info in batiments_universite.items():
            if "ufr" in info and info["ufr"].lower() in question_lower:
                keywords.append(info["ufr"].lower())
                keywords.append(batiment.lower())
            if "ufr" in info and any(discipline in question_lower for discipline in
                                     ["philo", "socio", "psycho", "segmi", "lettres", "politique", "droit", "eco"]):
                if "philo" in question_lower and "Philosophie" in info.get("ufr", ""):
                    keywords.extend(["philosophie", batiment.lower()])
                if "socio" in question_lower and "Sociologie" in info.get("ufr", ""):
                    keywords.extend(["sociologie", batiment.lower()])
                if "psycho" in question_lower and "Psychologie" in info.get("ufr", ""):
                    keywords.extend(["psychologie", batiment.lower()])
                if "segmi" in question_lower and "Économie" in info.get("ufr", ""):
                    keywords.extend(["segmi", "economie", batiment.lower()])
                if "lettres" in question_lower and "Lettres" in info.get("ufr", ""):
                    keywords.extend(["lettres", batiment.lower()])
                if "politique" in question_lower and "Politique" in info.get("ufr", ""):
                    keywords.extend(["politique", batiment.lower()])

    if ("association" in question_lower or "club" in question_lower or "asso" in question_lower):
        if "sport" in question_lower:
            keywords.extend(["association", "sport", "altiski", "cheerleading", "laocho", "nav"])
        elif "cheerleading" in question_lower:
            keywords.extend(["cheerleading", "association", "sport"])
        elif "voile" in question_lower or "bateau" in question_lower or "nautique" in question_lower:
            keywords.extend(["nav", "voile", "association", "sport"])
        elif "théâtre" in question_lower or "theatre" in question_lower:
            keywords.extend(["théâtre", "impunis", "indifferents", "ptdr"])
        elif "musique" in question_lower:
            keywords.extend(["musique", "dix de choeur", "melodix", "volt"])
        elif "débat" in question_lower or "debat" in question_lower or "éloquence" in question_lower:
            keywords.extend(["éloquence", "débat", "revolte toi", "mun", "eloquentia", "lysias"])
        elif "écologie" in question_lower or "ecologie" in question_lower or "environnement" in question_lower:
            keywords.extend(["écologie", "unis vers"])
        elif "représentation" in question_lower or "étudiant" in question_lower or "syndicat" in question_lower:
            keywords.extend(["représentation étudiante", "acfa", "faun", "unef", "ugen", "union etudiante"])
        elif "media" in question_lower or "médias" in question_lower or "lecture" in question_lower or "écriture" in question_lower or "livre" in question_lower:
            keywords.extend(["médias", "lecture", "écriture", "atelier decriture", "lili blooms", "pile a lire"])
        elif "audiovisuel" in question_lower or "cinéma" in question_lower or "cinema" in question_lower or "film" in question_lower:
            keywords.extend(["audiovisuel", "cinéma", "lcc production", "nuits noires", "cine rebelle"])
        elif "science" in question_lower or "scientifique" in question_lower:
            keywords.extend(["culture scientifique", "rcva"])
        elif "solidarité" in question_lower or "entraide" in question_lower:
            keywords.extend(["solidarité", "entraide", "aumonerie", "asega", "emf", "ucph", "uejf"])
        elif "caritatif" in question_lower or "humanitaire" in question_lower:
            keywords.extend(["caritatif", "amnesty", "lathena", "unicef"])
        elif "culture" in question_lower or "monde" in question_lower or "international" in question_lower:
            keywords.extend(["cultures du monde", "amicale senegalais", "paris nanterre maroc"])
        elif "citoyenneté" in question_lower or "politique" in question_lower:
            keywords.extend(["citoyenneté", "cercle marxiste", "poing leve"])
        elif "filière" in question_lower or "filiere" in question_lower or "ssa" in question_lower:
            keywords.extend(
                ["association de filiere", "ssa", "promet", "hypothemuse", "gang", "enape", "asega"])
        elif "staps" in question_lower:
            keywords.extend(["staps", "rhinos"])
        elif "psychologie" in question_lower or "psycho" in question_lower or "spse" in question_lower:
            keywords.extend(["psychologie", "spse", "psychx", "alhumes", "caress"])
        elif "droit" in question_lower or "dsp" in question_lower:
            keywords.extend(["droit", "science politique", "dsp", "dl"])
        elif "philo" in question_lower or "philosophie" in question_lower or "phillia" in question_lower:
            keywords.extend(["philosophie", "phillia", "cine rebelle"])
        elif "économie" in question_lower or "economie" in question_lower or "gestion" in question_lower or "segmi" in question_lower:
            keywords.extend(["économie", "gestion", "segmi", "west street"])
        else:
            keywords.append("association")
    if "vie étudiante" in question_lower or "aide étudiant" in question_lower or "soutien étudiant" in question_lower or "entraide" in question_lower:
        keywords.extend(["vie étudiante", "aide", "solidarité", "entraide", "soutien"])
        if "financier" in question_lower or "argent" in question_lower or "bourse" in question_lower:
            keywords.extend(["aide financière", "bourse", "finance"])
        if "logement" in question_lower or "habitation" in question_lower:
            keywords.extend(["logement", "résidence"])
        if "administratif" in question_lower or "démarche" in question_lower:
            keywords.extend(["aide administrative", "démarche"])
        if "santé" in question_lower or "médical" in question_lower:
            keywords.extend(["santé", "médical", "psychologique"])

    association_keywords = {
        "asso", "association", "associations", "club", "clubs",
        "bde", "bds", "bda", "aca2", "étudiant", "étudiante",
        "étudiants", "étudiantes", "vie", "campus", "universitaire",
        "membre", "adhérer", "adhésion", "inscription", "activité",
        "activités", "culture", "sport", "artistique", "théâtre",
        "musique", "danse", "photographie", "cinéma", "humanitaire",
        "politique", "religion", "festival", "événement", "projet",
        "bureau", "liste", "élection"
    }

    student_life_support_associations = {
        "aide financière": ["ucph", "uejf", "lathena", "unicef"],
        "solidarité": ["asega", "emf", "aumonerie", "unicef", "lathena"],
        "entraide": ["ucph", "uejf", "asega", "emf"],
        "soutien psychologique": ["caress", "psychx"],
        "aide administrative": ["ucph", "uejf", "asega"],
        "représentation": ["acfa", "faun", "unef", "ugen", "union etudiante"]
    }

    question_lower = question.lower()
    is_association_question = any(word in question_lower for word in association_keywords)

    if is_association_question:
        keywords = [word for word in keywords if
                    word not in ["contact", "telephone", "email"]]  # Enlever les mots-clés de contact
        keywords.extend(["association", "aca2", "etudiant"])

        if any(word in question_lower for word in
               ["culture", "culturel", "culturelle", "art", "théâtre", "musique", "danse"]):
            keywords.extend(["culture", "artistique"])
            if "art" in question_lower:
                keywords.append("art")
            if "théâtre" in question_lower or "theatre" in question_lower:
                keywords.append("theatre")
            if "musique" in question_lower:
                keywords.append("musique")
            if "danse" in question_lower:
                keywords.append("danse")
    if "handicap" in question_lower or "accessibilité" in question_lower or "sha" in question_lower:
        keywords.extend(["handicap", "accessibilite", "sha", "service"])

        # Services de restauration
    if "resto" in question_lower or "restaurant" in question_lower or "cafétéria" in question_lower or "manger" in question_lower or "repas" in question_lower:
        keywords.extend(["restauration", "crous", "cafeteria", "repas", "resto", "restaurant", "ru"])

        # Services à la vie étudiante
    if "service étudiant" in question_lower or "vie étudiante" in question_lower or "suio" in question_lower:
        keywords.extend(["service", "vie etudiante", "suio", "aide"])

        # Transports
    if "transport" in question_lower or "bus" in question_lower or "métro" in question_lower or "train" in question_lower or "rer" in question_lower or "imagine r" in question_lower:
        keywords.extend(["transport", "navigo", "imagine-r", "mobilite", "bus"])

    return keywords


def answer_building_question(question):
    """Répond aux questions concernant les bâtiments de l'université"""
    import time
    import random

    # Simuler un délai de traitement (environ 3 secondes)
    time.sleep(random.uniform(2.8, 3.2))

    question_lower = question.lower()

    # Cas 1: Question sur un bâtiment spécifique par son nom
    for batiment, info in batiments_universite.items():
        if batiment.lower() in question_lower:
            reponse = f"Le bâtiment {batiment} (lettre {info['lettre']}) "
            if "ufr" in info:
                reponse += f"abrite {info['ufr']} "
            if "localisation" in info:
                reponse += f"et se trouve dans la partie {info['localisation']} du campus."
            else:
                reponse += "se trouve sur le campus de l'université Paris Nanterre."
            return reponse

    # Cas 2: Question sur une UFR spécifique
    for batiment, info in batiments_universite.items():
        if "ufr" in info:
            ufr_lower = info["ufr"].lower()
            if any(keyword in ufr_lower for keyword in ["philo", "philosophie"]) and "philo" in question_lower:
                return f"L'UFR de Philosophie se trouve dans le bâtiment {batiment} (lettre {info['lettre']}), situé dans la partie {info.get('localisation', 'ouest')} du campus."
            elif any(keyword in ufr_lower for keyword in ["socio", "sociologie"]) and "socio" in question_lower:
                return f"L'UFR de Sociologie se trouve dans le bâtiment {batiment} (lettre {info['lettre']}), situé dans la partie {info.get('localisation', 'ouest')} du campus."
            elif any(keyword in ufr_lower for keyword in ["psycho", "psychologie"]) and "psycho" in question_lower:
                return f"L'UFR de Psychologie se trouve dans le bâtiment {batiment} (lettre {info['lettre']}), situé dans la partie {info.get('localisation', 'ouest')} du campus."
            elif "politique" in ufr_lower and "politique" in question_lower:
                return f"L'UFR de Science Politique se trouve dans le bâtiment {batiment} (lettre {info['lettre']}), situé dans la partie {info.get('localisation', 'ouest')} du campus."
            elif "lettres" in ufr_lower and "lettres" in question_lower:
                return f"L'UFR Lettres, Langues, Arts se trouve dans le bâtiment {batiment} (lettre {info['lettre']})."
            elif "segmi" in question_lower or (
                    "économie" in question_lower or "economie" in question_lower or "gestion" in question_lower):
                # SEGMI n'est pas dans le dictionnaire, mais on peut ajouter une réponse spécifique
                return "L'UFR SEGMI (Sciences Économiques, Gestion, Mathématiques, Informatique) se trouve dans le bâtiment G (Allais), situé dans la partie sud du campus."

    # Cas 3: Question par lettre de bâtiment
    for lettre in ["a", "b", "c", "d", "e", "f", "g", "h", "l", "m", "n", "s", "v", "w"]:
        if f"bâtiment {lettre}" in question_lower or f"batiment {lettre}" in question_lower:
            for batiment, info in batiments_universite.items():
                if info["lettre"].lower() == lettre:
                    reponse = f"Le bâtiment {lettre.upper()} s'appelle {batiment}"
                    if "ufr" in info:
                        reponse += f" et abrite {info['ufr']}"
                    if "localisation" in info:
                        reponse += f". Il est situé dans la partie {info['localisation']} du campus."
                    else:
                        reponse += "."
                    return reponse

    # Cas 4: Question générale sur les bâtiments
    if "batiments" in question_lower or "bâtiments" in question_lower:
        return "Le campus de Paris Nanterre compte de nombreux bâtiments identifiés par des lettres (A à W). Par exemple, le bâtiment A (Remond) abrite l'UFR de Science Politique, le bâtiment G (Allais) se trouve au sud du campus, et la Maison de l'Étudiant (MDE) est située au centre-sud-ouest du campus."
    return None


def find_similar_question(existing_data, question):
    normalized_question = question.lower().strip()
    current_keywords = set(extract_keywords(normalized_question))
    best_match = None
    best_score = 0

    building_answer = answer_building_question(question)
    if building_answer:
        return building_answer

    for saved_question, answer in existing_data.items():
        saved_keywords = set(extract_keywords(saved_question.lower().strip()))
        text_similarity = fuzz.token_sort_ratio(saved_question.lower(), normalized_question)

        keyword_intersection = len(current_keywords.intersection(saved_keywords))
        keyword_union = len(current_keywords.union(saved_keywords))
        keyword_similarity = (keyword_intersection / keyword_union * 100) if keyword_union > 0 else 0
        combined_similarity = (keyword_similarity * 0.7) + (text_similarity * 0.3)

        current_subject = get_main_subject(normalized_question)
        saved_subject = get_main_subject(saved_question.lower())

        if current_subject and saved_subject and current_subject != saved_subject:
            combined_similarity *= 0.5

        if combined_similarity > 75 and combined_similarity > best_score:
            best_score = combined_similarity
            best_match = answer
            print(f"Question potentiellement similaire trouvée: '{saved_question}' (score: {combined_similarity:.1f}%)")

    if best_score > 75:
        return best_match
    return None


def get_main_subject(question):
    patterns = [
        r"est.ce qu'il y a des? ([\w\s]+) (à|a|au|aux|dans|en)",
        r"y a.t.il des? ([\w\s]+) (à|a|au|aux|dans|en)",
        r"existe.t.il des? ([\w\s]+) (à|a|au|aux|dans|en)"
    ]

    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            return match.group(1).strip()

    keywords = extract_keywords(question)
    important_words = [word for word in keywords if
                       len(word) > 3 and word not in ["asso", "association", "université", "campus"]]

    if important_words:
        return important_words[0]
    return None


def load_data_from_file(filename="questions_responses.json"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"Fichier de cache chargé. {len(data)} questions en mémoire.")
            return data
    except FileNotFoundError:
        print(f"Fichier {filename} non trouvé. Création d'un nouveau cache.")
        return {}
    except json.JSONDecodeError:
        print(f"Erreur de décodage de {filename}. Le fichier est peut-être corrompu.")
        import shutil
        shutil.copy(filename, f"{filename}.bak")
        return {}


def answer_university_contact_question(question):
    """Répond aux questions concernant l'université avec les informations prédéfinies"""
    question_lower = question.lower()

    university_info = {
        "nom": "Université Paris Nanterre",
        "adresse": "200 avenue de la République, 92001 Nanterre Cedex",
        "telephone": "01 40 97 72 00",
        "site_web": "https://www.parisnanterre.fr/",
        "rer": "Prendre la ligne A du R.E.R., direction Saint-Germain-en-Laye, et descendre à la station « Nanterre Université ».",
        "train": "Prendre le train Ligne L à la gare Saint-Lazare, direction « Nanterre université » ou « Cergy-le-haut », et descendre à la station « Nanterre Université ».",
        "bus": "– ligne 259 « Nanterre-Anatole France – Saint-Germain-en-Laye RER »\n– ligne 304 « Nanterre Place de la Boule – Asnières-Gennevilliers Les Courtilles » : arrêt Nanterre Université\n– ligne 367 « Rueil-Malmaison RER – Pont de Bezons » : arrêt Université Paris Nanterre Université RER\n– ligne 378 « Nanterre-Ville RER – Asnières-Gennevilliers Les Courtilles » : arrêt Nanterre Université",
        "route": "L'université est accessible par les autoroutes A86 et A14. Des possibilités de stationnement gratuit sont disponibles autour du campus.",
        "temps": "Les différents moyens de transports placent le campus de Nanterre à 5 minutes du quartier de la Défense, à 10 minutes de la place Charles de Gaulle-Etoile et à 20 minutes du quartier latin.",
        "velo": "Par l'entrée Noël Pons et par l'entrée avenue de la république. Des arceaux pour accrocher votre vélo sont situés a proximité des entrées de plusieurs bâtiments. Une station Véligo est localisée sur le parvis de l'université. Elle est accessible avec un passe Navigo et équipée de bornes de recharge pour les vélos à assistance électrique."
    }

    # Vérification si la question concerne spécifiquement l'université et une demande d'info précise
    university_terms = ["université", "paris nanterre", "univ", "fac", "campus"]
    university_mentioned = any(term in question_lower for term in university_terms)

    if not university_mentioned:
        return None

    # Vérifier si c'est une demande d'information spécifique
    is_specific_request = False

    # Question sur l'adresse
    if any(term in question_lower for term in ["adresse", "où se trouve", "où est", "localisation", "situé", "située"]):
        is_specific_request = True
        return f"{university_info['nom']}\n{university_info['adresse']}"

    # Question sur le téléphone ou contact
    elif any(term in question_lower for term in ["téléphone", "numéro", "contact", "appeler", "joindre"]):
        is_specific_request = True
        return f"{university_info['nom']}\nStandard : {university_info['telephone']}"

    # Question sur le site web
    elif any(term in question_lower for term in ["site", "site web", "site internet", "page web", "internet"]):
        is_specific_request = True
        return f"Le site web officiel de {university_info['nom']} est : {university_info['site_web']}"

    # Question sur les moyens de transport
    elif any(term in question_lower for term in
             ["rer", "r.e.r", "train", "sncf", "bus", "autobus", "voiture", "route", "vélo", "velo", "bicyclette",
              "veligo", "transport", "venir", "accès", "acces", "arriver", "autoroute", "aller", "comment s'y rendre"]):
        is_specific_request = True

    if not is_specific_request:
        return None
    # Question générale sur les transports
    elif any(term in question_lower for term in
             ["transport", "venir", "accès", "acces", "arriver", "comment s'y rendre"]):
        response = "Accès à l'Université Paris Nanterre :\n\n"
        response += "En transports en commun :\n"
        response += f"- Par le R.E.R. : {university_info['rer']}\n"
        response += f"- Par le train : {university_info['train']}\n"
        response += f"- Par le bus : {university_info['bus']}\n\n"
        response += f"Par la route : {university_info['route']}\n\n"
        response += f"En vélo : {university_info['velo']}\n\n"
        response += f"{university_info['temps']}"
        return response

    else:
        response = f"{university_info['nom']}\n"
        response += f"Adresse : {university_info['adresse']}\n"
        response += f"Standard : {university_info['telephone']}\n"
        response += f"Site web : {university_info['site_web']}\n\n"
        response += "Pour des informations plus précises sur les moyens d'accès, posez une question spécifique sur les transports."
        return response


def find_similar_question(existing_data, question):
    normalized_question = question.lower().strip()
    current_keywords = set(extract_keywords(normalized_question))
    best_match = None
    best_score = 0

    # Vérifier d'abord si c'est une question spécifique sur les contacts de l'université
    university_contact_answer = answer_university_contact_question(question)
    if university_contact_answer:
        return university_contact_answer

    # Vérifier si c'est une question sur les bâtiments
    building_answer = answer_building_question(question)
    if building_answer:
        return building_answer

    # Le reste de la fonction reste inchangé
    for saved_question, answer in existing_data.items():
        saved_keywords = set(extract_keywords(saved_question.lower().strip()))
        text_similarity = fuzz.token_sort_ratio(saved_question.lower(), normalized_question)

        keyword_intersection = len(current_keywords.intersection(saved_keywords))
        keyword_union = len(current_keywords.union(saved_keywords))
        keyword_similarity = (keyword_intersection / keyword_union * 100) if keyword_union > 0 else 0
        combined_similarity = (keyword_similarity * 0.7) + (text_similarity * 0.3)

        current_subject = get_main_subject(normalized_question)
        saved_subject = get_main_subject(saved_question.lower())

        if current_subject and saved_subject and current_subject != saved_subject:
            combined_similarity *= 0.5

        if combined_similarity > 75 and combined_similarity > best_score:
            best_score = combined_similarity
            best_match = answer
            print(f"Question potentiellement similaire trouvée: '{saved_question}' (score: {combined_similarity:.1f}%)")

    if best_score > 75:
        return best_match
    return None


def extract_relevant_content(soup, question_keywords):
    relevant_sections = []

    for heading in soup.find_all(['h1', 'h2', 'h3']):
        heading_text = heading.get_text().lower()
        if any(keyword in heading_text for keyword in question_keywords):
            section_content = [heading.get_text()]
            for sibling in heading.find_next_siblings():
                if sibling.name in ['h1', 'h2', 'h3']:
                    break
                if sibling.name in ['p', 'ul', 'ol', 'table']:
                    section_content.append(sibling.get_text())
            relevant_sections.append(" ".join(section_content))

    if not relevant_sections:
        main_content = soup.select_one('#content, main, article, .content')
        if main_content:
            relevant_sections.append(main_content.get_text()[:1500])
        else:
            relevant_sections.append(soup.get_text()[:1000])
    return "\n".join(relevant_sections)


def group_similar_pages_by_content(url_text_dict, threshold=85):
    grouped = []
    visited = set()

    urls = list(url_text_dict.keys())
    for i, url1 in enumerate(urls):
        if url1 in visited:
            continue
        group = [url1]
        visited.add(url1)
        for j in range(i + 1, len(urls)):
            url2 = urls[j]
            if url2 in visited:
                continue
            score = fuzz.ratio(url_text_dict[url1], url_text_dict[url2])
            if score >= threshold:
                group.append(url2)
                visited.add(url2)
        grouped.append(group)
    return grouped


async def get_text_from_url_with_delay(url, cached_data, delay=2, retries=3):
    if url in cached_data:
        return cached_data[url]

    attempt = 0
    while attempt < retries:
        try:
            await asyncio.sleep(delay)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        print(f"Erreur: statut {response.status} pour {url}")
                        attempt += 1
                        continue
                    page = await response.text()

            soup = BeautifulSoup(page, 'html.parser')

            for script in soup(['script', 'style']):
                script.decompose()

            content_texts = []

            for selector in ['#content', 'main', 'article', '.content', '#main-content', '.entry-content']:
                content = soup.select_one(selector)
                if content:
                    # Extraire les titres et paragraphes avec leur hiérarchie
                    for element in content.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'table']):
                        if element.name.startswith('h'):
                            content_texts.append(f"\n## {element.get_text().strip()}")
                        elif element.name == 'p':
                            content_texts.append(element.get_text().strip())
                        elif element.name in ['ul', 'ol']:
                            for li in element.find_all('li'):
                                content_texts.append(f"- {li.get_text().strip()}")
                        elif element.name == 'table':
                            # Extraction simplifiée des tableaux
                            content_texts.append("Tableau trouvé avec les informations suivantes:")
                            for tr in element.find_all('tr'):
                                row_text = ' | '.join([td.get_text().strip() for td in tr.find_all(['td', 'th'])])
                                content_texts.append(f"  {row_text}")
                    break  # Utiliser le premier sélecteur qui fonctionne

            # Si aucun contenu structuré n'a été trouvé, utiliser le texte brut
            if not content_texts:
                content_texts = [soup.get_text(separator=' ')]

            text = '\n'.join(content_texts)

            # Nettoyer le texte pour supprimer les espaces multiples
            text = re.sub(r'\s+', ' ', text)
            text = re.sub(r'\n\s*\n', '\n\n', text)

            cached_data[url] = text
            save_cached_data(cached_data)
            return text
        except Exception as e:
            print(f"Erreur lors de la récupération de {url} (tentative {attempt + 1}): {e}")
            attempt += 1
            delay = random.uniform(3, 5)
            if attempt == retries:
                print(f"Échec de la récupération de {url} après {retries} tentatives.")
                return ""


def extract_specific_information(soup, question_keywords):
    """Extrait des informations spécifiques basées sur les mots-clés de la question"""
    relevant_info = []

    for keyword in question_keywords:
        # 1. Chercher dans les titres et contenus adjacents
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
            if keyword.lower() in heading.get_text().lower():
                section = [f"SECTION: {heading.get_text()}"]
                current = heading.next_sibling
                # Collecter les paragraphes suivant le titre jusqu'au prochain titre
                while current and current.name not in ['h1', 'h2', 'h3', 'h4']:
                    if current.name in ['p', 'ul', 'ol', 'div'] and current.get_text().strip():
                        section.append(current.get_text().strip())
                    current = current.next_sibling
                relevant_info.append('\n'.join(section))

        # 2. Chercher dans les paragraphes
        for para in soup.find_all(['p', 'li']):
            text = para.get_text().lower()
            if keyword.lower() in text:
                relevant_info.append(f"INFORMATION: {para.get_text().strip()}")

        # 3. Chercher dans les tableaux pour les informations structurées
        for table in soup.find_all('table'):
            table_has_keyword = False
            for cell in table.find_all(['th', 'td']):
                if keyword.lower() in cell.get_text().lower():
                    table_has_keyword = True
                    break

            if table_has_keyword:
                table_data = ["TABLE:"]
                for row in table.find_all('tr'):
                    cells = row.find_all(['th', 'td'])
                    if cells:
                        row_text = ' | '.join(cell.get_text().strip() for cell in cells)
                        table_data.append(row_text)
                relevant_info.append('\n'.join(table_data))

    # Si des informations spécifiques sont trouvées, les retourner
    if relevant_info:
        return '\n\n'.join(relevant_info)
    return None


async def get_multiple_texts(urls, cached_data):
    tasks = []
    for url in urls:
        if url in cached_data:
            continue
        tasks.append(get_text_from_url_with_delay(url, cached_data))
    if tasks:
        await asyncio.gather(*tasks)
    return [cached_data.get(url, "") for url in urls]


def ask_ollama_improved(context, question):
    is_association_question = any(
        term in question.lower() for term in ["association", "club", "asso", "activité étudiante", "existe-t-il"])
    is_student_life_question = any(term in question.lower() for term in
                                   ["aide", "soutien", "entraide", "vie étudiante", "solidarité", "accompagnement"])
    is_crous_question = any(
        term in question.lower() for term in ["crous", "resto", "restaurant", "cafétéria", "restauration", "repas"])
    is_transport_question = any(
        term in question.lower() for term in ["transport", "bus", "métro", "imagine r", "train", "rer", "navigo"])
    is_handicap_question = any(
        term in question.lower() for term in ["handicap", "sha", "accessibilité", "situation de handicap"])

    system_prompt = """Tu es un assistant universitaire précis qui répond de manière COMPLÈTE et DÉTAILLÉE."""

    if is_crous_question:
        system_prompt += """
        INSTRUCTION CRITIQUE: Cette question concerne le CROUS de Versailles.

        Tu dois:
        1. Toujours préciser qu'il s'agit du CROUS de Versailles
        2. Fournir les coordonnées exactes (numéro de téléphone, email, site) si elles sont présentes dans les données
        3. Indiquer les différents moyens de contacter le CROUS de Versailles
        4. Ne pas confondre avec d'autres CROUS régionaux

        Le numéro de téléphone du CROUS de Versailles est le 09 72 59 65 65 et son site web : www.crous-versailles.fr
        """

    if is_association_question and not is_crous_question:
        system_prompt += """
        INSTRUCTION CRITIQUE: Cette question concerne UNIQUEMENT les associations étudiantes de l'université.

        NE MENTIONNE PAS LE CROUS DE VERSAILLES dans ta réponse sauf s'il y a une relation directe et explicite.

        Tu dois:
        1. Lister plusieurs associations dans différents domaines
        2. Présenter leurs activités principales
        3. Indiquer leurs contacts si disponibles
        4. Mentionner le site des associations: https://ufr-lce.parisnanterre.fr/associations
        """

    if is_transport_question:
        system_prompt += """
            INSTRUCTION CRITIQUE: Cette question concerne les transports pour les étudiants.

            Tu dois:
            1. Donner des informations sur les cartes Imagine R ou Navigo si pertinent
            2. Préciser les réductions pour étudiants
            3. Mentionner les lignes de transport desservant l'université si connues
            4. Indiquer les démarches à suivre pour obtenir les cartes de transport
            """

    if is_handicap_question:
        system_prompt += """
            INSTRUCTION CRITIQUE: Cette question concerne le Service Handicap et Accessibilité (SHA).

            Tu dois:
            1. Décrire précisément les services offerts par le SHA
            2. Indiquer comment contacter le service (numéro, email, bureau)
            3. Préciser les démarches à effectuer pour bénéficier d'aménagements
            4. Mentionner les horaires d'ouverture si disponibles
            """

    if is_student_life_question:
        system_prompt += """
        INSTRUCTION CRITIQUE: Cette question concerne UNIQUEMENT les associations d'aide à la vie étudiante. 

        Tu dois EXCLUSIVEMENT mentionner les associations qui:
        1. Fournissent une aide directe et concrète aux étudiants (aide financière, logement, alimentaire, psychologique)
        2. Offrent des services de soutien et d'accompagnement (administratif, juridique, santé)
        3. Sont spécialisées dans la solidarité et l'entraide étudiante
        4. Défendent les intérêts des étudiants auprès de l'administration

        IGNORER COMPLÈTEMENT:
        - Les associations culturelles
        - Les associations sportives
        - Les associations académiques/disciplinaires
        - Les associations de filières qui n'ont pas d'actions concrètes d'aide aux étudiants

        Pour chaque association pertinente, précise:
        - Son nom complet
        - Ses services concrets d'aide aux étudiants
        - Comment la contacter
        """
    else:
        system_prompt += """
        IMPORTANT: Identifie d'abord la catégorie exacte de la question (sport, art martial, danse, association, logement, bourse, restauration, transport ,etc.).
        Ne confonds pas les arts martiaux avec les danses - ce sont des catégories distinctes.
        Quand il s'agit de sports ou d'associations, donne des informations exhaustives incluant les horaires, lieux, contacts, site internet et modalités d'inscription si disponibles.
        """

    system_prompt += """
    Réponds uniquement en fonction des informations fournies, mais assure-toi que ta réponse soit la plus complète possible.
    Structure ta réponse de manière claire avec des points clés si nécessaire.
    N'extrais pas seulement les contacts - ils doivent compléter l'information, pas la remplacer.
    Si l'information n'est pas complète dans les données, précise quelles informations manquent.
    """
    urls_in_context = []
    for line in context.split('\n'):
        if line.startswith("Source: "):
            urls_in_context.append(line.replace("Source: ", "").strip())

    most_relevant_url = ""
    if urls_in_context:
        most_relevant_url = urls_in_context[0]

    system_prompt += """
        CRITIQUE: Ta mission est d'EXTRAIRE et de SYNTHÉTISER l'information pertinente pour la question posée.

        1. Identifie les passages clés dans les données fournies qui répondent directement à la question
        2. Fais une synthèse précise et complète des informations pertinentes
        3. Structure ta réponse de manière claire (titres, points clés, listes si nécessaire)
        4. INCLUS ABSOLUMENT les informations de contact si elles sont présentes (téléphone, email, site web)
        5. Si plusieurs sources contiennent des informations pertinentes, combine-les dans une réponse cohérente

        TA RÉPONSE DOIT ÊTRE UTILE ET ACTIONNABLE - l'utilisateur doit pouvoir agir sur base de ta réponse.
        """

    full_context = f"""Voici les informations trouvées sur les sites web:
    {context}

    QUESTION: {question}

    Ta tâche est d'extraire uniquement les informations pertinentes pour répondre à cette question de la manière la plus précise et complète possible.
    """

    response = ollama.chat(
        model="mistral",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_context}
        ]
    )
    content = response['message']['content']

    if is_association_question or "association" in question.lower() or any(
            x in content.lower() for x in ["association", "aca2", "club étudiant"]):
        if not content.endswith('.'):
            content += '.'

        content += "\n\nPour plus d'informations sur toutes les associations de l'université, consultez: https://ufr-lce.parisnanterre.fr/associations"

    if not any(url in content for url in urls_in_context):
        content += f"\n\nPour plus d'informations, consultez: {most_relevant_url}"

    source_url = None
    for url in urls_in_context:
        if url in content:
            source_url = url
            break

    if not source_url and urls_in_context:
        source_url = urls_in_context[0]
        content += f"\n\nSource: {source_url}"

    return content


async def find_info_for_question(question, data, urls, cached_data):
    similar_answer = find_similar_question(data, question)
    if similar_answer:
        return similar_answer

    keywords = extract_keywords(question.lower())

    if isinstance(urls, dict):
        relevant_urls = []
        question_lower = question.lower()

        categories = {
            "crous": ["crous", "resto", "restaurant", "cafet", "repas"],
            "association": ["association", "club", "aca2", "étudiant", "activité"],
            "transport": ["transport", "bus", "métro", "train", "rer", "imagine"],
            "handicap": ["handicap", "sha", "accessibilité"],
            "sport": ["sport", "suaps", "activité physique", "musculation"]
        }

        detected_categories = []
        for category, terms in categories.items():
            if any(term in question_lower for term in terms):
                detected_categories.append(category)

        if not detected_categories:
            for url, tags in urls.items():
                if any(keyword in ' '.join(tags).lower() for keyword in keywords):
                    relevant_urls.append(url)
        else:
            for category in detected_categories:
                category_urls = []
                for url, tags in urls.items():
                    if category in ' '.join(tags).lower() or any(
                            term in ' '.join(tags).lower() for term in categories[category]):
                        category_urls.append(url)

                relevant_urls.extend(category_urls[:3])

        # Limiter à 10 URLs au total
        relevant_urls = relevant_urls[:10]
    else:
        # Utiliser la méthode existante si urls est une liste
        relevant_urls = [url for url in urls if any(keyword in url.lower() for keyword in keywords)][:10]

    # Si toujours pas d'URL pertinente, prendre quelques URLs par défaut
    if not relevant_urls and isinstance(urls, dict):
        relevant_urls = list(urls.keys())[:10]
    elif not relevant_urls:
        relevant_urls = urls[:10]

    print(f"Recherche dans {len(relevant_urls)} URLs pertinentes...")
    print(f"Recherche dans {len(relevant_urls)} URLs pertinentes...")

    # Récupérer et traiter le contenu des URLs
    context = ""  # Initialize context here
    results = []  # We'll use this to track successful results

    for url in relevant_urls:
        text = await get_text_from_url_with_delay(url, cached_data)
        if text:
            print(f"Type of text: {type(text)}")
            try:
                context += f"\nSource: {url}\n"
                context += f"Informations: {text[:3000]}...\n\n"
                results.append((url, text))  # Add to results if successful
            except TypeError:
                context += f"\nSource: {url}\n"
                context += f"Informations: {str(text)}\n\n"
                results.append((url, str(text)))  # Add to results if successful

    if not results:
        return "Désolé, je n'ai pas pu extraire d'informations des sites web pertinents pour répondre à votre question."

    # Construire un contexte plus riche avec les résultats
    context = ""
    for url, text in results:
        # Limiter la taille du texte à 3000 caractères pour chaque URL
        context += f"\nSource: {url}\n"
        context += f"Informations: {text[:3000]}...\n\n"

    response = ask_ollama_improved(context, question)

    data[question] = response
    save_data_to_file(data)

    return response


def get_relevant_urls(urls, question, max_urls=5):
    keywords = extract_keywords(question.lower())
    question_lower = question.lower()

    url_categories = {
        "sport": [url for url in urls if "suaps" in url or "/les-sports-et-activites" in url],
        "association": [url for url in urls if "aca2" in url or "associations" in url],
        "logement": [url for url in urls if "logement" in url or "crous" in url and "residence" in url],
        "bourse": [url for url in urls if "bourse" in url or "aide" in url],
        "general": [url for url in urls if "contacts" in url or "accueil" in url],
        "arts_martiaux": [url for url in urls if
                          "combat" in url or "judo" in url or "boxe" in url or "self-defense" in url],
        "vie_etudiante": [url for url in urls if "solidarite" in url or "entraide" in url or "soutien" in url],
        "restauration": [url for url in urls if any(
            term in url.lower() for term in ["resto", "restaurant universitaire", "cafeteria", "repas"])],
        "vie etudiante": [url for url in urls if
                          any(term in url.lower() for term in ["vie-etudiante", "suio", "service", "aide-a-la-vie"])],
        "handicap": [url for url in urls if any(term in url.lower() for term in ["handicap", "sha", "accessibilite"])],
        "transport": [url for url in urls if any(term in url.lower() for term in ["transport", "mobilite", "imagine"])],
    }

    category_scores = {
        "restauration": sum(1 for kw in keywords if kw in ["restauration", "cafeteria", "repas", "resto", "restaurant", "ru"]),
        "vie_etudiante": sum(1 for kw in keywords if kw in ["service", "vie etudiante", "suio", "aide"]),
        "handicap": sum(1 for kw in keywords if kw in ["handicap", "accessibilite", "sha"]),
        "transport": sum(1 for kw in keywords if kw in ["transport", "navigo", "imagine-r", "mobilite", "bus"]),
        "sport": sum(1 for kw in keywords if kw in ["sport", "suaps", "activite", "physique"]),
        "association": sum(1 for kw in keywords if kw in ["association", "club", "etudiant"]),
        "logement": sum(1 for kw in keywords if kw in ["logement", "residence", "habiter"]),
        "bourse": sum(1 for kw in keywords if kw in ["bourse", "aide", "finance"]),
        "general": 1
    }

    main_category = max(category_scores, key=category_scores.get)
    selected_urls = url_categories[main_category][:max_urls - 2] + url_categories["general"][:2]
    if len(selected_urls) < max_urls - 2:
        selected_urls += url_categories["general"][:max_urls - len(selected_urls)]
    else:
        selected_urls += url_categories["general"][:2]

    return selected_urls[:max_urls]


def main():
    print("Bienvenue dans l'outil de recherche d'informations avec Ollama Mistral!")
    print("Posez votre question (par exemple: 'Quel est le numéro de téléphone du Crous ?')")

    data = load_data_from_file()
    cached_data = load_cached_data()

    urls = {
        "https://api.parisnanterre.fr/aide-a-la-vie-etudiante": ["service", "aide", "vie étudiante"],
        "https://api.parisnanterre.fr/accueil-sha": ["service", "handicap", "sha", "aide"],
        "https://api.parisnanterre.fr/faq": ["service", "handicap", "faq", "sha", "aide"],
        "https://api.parisnanterre.fr/accueil-suio": ["service", "aide"],
        "https://www.crous-versailles.fr/": ["services étudiants", "aides financières", "solidarité étudiante"],
        "https://www.crous-versailles.fr/contacts/": ["contacts", "aide étudiante", "CROUS", "logement"],
        "https://www.crous-versailles.fr/contacts/bourses-et-aides-financieres/": ["bourses", "aides financières",
                                                                                   "CROUS", "précarité étudiante"],
        "https://www.crous-versailles.fr/contacts/social-et-accompagnement/": ["aide sociale", "accompagnement",
                                                                               "CROUS", "solidarité étudiante"],
        "https://www.crous-versailles.fr/contacts/logement-et-vie-en-residence/": ["logement étudiant",
                                                                                   "vie en résidence", "CROUS",
                                                                                   "aide au logement"],
        "https://www.crous-versailles.fr/contacts/compte-izly/": ["compte Izly", "CROUS", "services étudiants",
                                                                  "paiement universitaire"],
        "https://www.crous-versailles.fr/contacts/contribution-vie-etudiante-et-de-campus-cvec/": ["CVEC",
                                                                                                   "vie étudiante",
                                                                                                   "contribution universitaire",
                                                                                                   "CROUS"],
        "https://www.iledefrance-mobilites.fr/titres-et-tarifs": ["transport"],
        "https://www.iledefrance-mobilites.fr/titres-et-tarifs/detail/forfait-imagine-r-scolaire": ["transport"],
        "https://www.iledefrance-mobilites.fr/titres-et-tarifs/detail/forfait-imagine-r-etudiant": ["transport"],
        "https://www.iledefrance-mobilites.fr/imagine-r/simulateur": ["transport"],
        "https://www.iledefrance-mobilites.fr/imagine-r#slice": ["transport"],
        "https://www.iledefrance-mobilites.fr/aide-et-contacts/nous-ecrire?type=information&motif=objets-trouves": ["transport"],
        "https://www.iledefrance-mobilites.fr/aide-et-contacts": ["transport"],
        "https://www.iledefrance-mobilites.fr/aide-et-contacts/generalites-supports-validations": ["transport"],
        "https://www.iledefrance-mobilites.fr/aide-et-contacts/generalites-supports-validations/comment-obtenir-un-forfait-imagine-r-et-ou-une-carte-de-transport-scolaire": ["transport"],
        "https://www.1jeune1solution.gouv.fr/logements/annonces?annonce-de-logement%5Brange%5D%5Bsurface%5D=0%3A500&annonce-de-logement%5Brange%5D%5Bprix%5D=0%3A3000": ["logement"],
        "https://www.1jeune1solution.gouv.fr/logements/aides-logement": ["logement"],
        "https://bienvenue.parisnanterre.fr/vie-du-campus/restauration-et-autres-lieux-de-convivialite": ["service", "restaurant", "restauration", "cafet", "cafétariat"],
        "https://www.1jeune1solution.gouv.fr/logements/conseils": ["logement"],
        "https://suaps.parisnanterre.fr/la-piscine": ["sport", "suaps", "activités nautiques"],
        "https://suaps.parisnanterre.fr/la-salle-cardio": ["sport", "suaps", "éducation corporelle et remise en forme",
                                                           "fitness"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites": ["sport", "suaps"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/les-sports-collectifs": ["sport", "suaps",
                                                                                         "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/basket-ball": ["sport", "suaps", "basket-ball",
                                                                               "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/futsal": ["sport", "suaps", "futsal",
                                                                          "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/handball": ["sport", "suaps", "handball",
                                                                            "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/rugby": ["sport", "suaps", "rugby", "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/tchoukball-kabadji": ["sport", "suaps", "tchoukball",
                                                                                      "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/volley-ball": ["sport", "suaps", "volley-ball",
                                                                               "sport collectif"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/les-sports-individuels": ["sport", "suaps",
                                                                                          "sport individuel"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/athletisme": ["sport", "suaps", "athlétisme",
                                                                              "sport individuel"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/escalade": ["sport", "suaps", "escalade",
                                                                            "sport individuel"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/tir-a-larc": ["sport", "suaps", "tir à l'arc",
                                                                              "sport individuel"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/les-sports-de-raquettes": ["sport", "suaps",
                                                                                           "sport de raquettes"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/badminton": ["sport", "suaps", "badminton",
                                                                             "sport de raquettes"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/tennis": ["sport", "suaps", "tennis",
                                                                          "sport de raquettes"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/tennis-de-table": ["sport", "suaps", "tennis de table",
                                                                                   "sport de raquettes"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/les-sports-de-combat": ["sport", "suaps",
                                                                                        "sport de combat"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/jiu-jitsu": ["sport", "suaps", "jiu-jitsu",
                                                                             "sport de combat"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/boxe": ["sport", "suaps", "boxe", "sport de combat"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/judo": ["sport", "suaps", "judo", "sport de combat"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/mma-grappling": ["sport", "suaps", "mma",
                                                                                 "sport de combat"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/self-defense": ["sport", "suaps", "self-defense",
                                                                                "sport de combat"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/education-corporelle-et-remise-en-forme": ["sport",
                                                                                                           "suaps",
                                                                                                           "éducation corporelle et remise en forme"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/education-posturale": ["sport", "suaps",
                                                                                       "éducation posturale",
                                                                                       "éducation corporelle et remise en forme"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/fitness": ["sport", "suaps", "fitness",
                                                                           "éducation corporelle et remise en forme"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/musculation": ["sport", "suaps", "musculation",
                                                                               "éducation corporelle et remise en forme"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/arts-du-mouvement": ["sport", "suaps",
                                                                                     "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/arts-du-cirque": ["sport", "suaps", "arts du cirque",
                                                                                  "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/atelier-choregraphie": ["sport", "suaps",
                                                                                        "atelier chorégraphie",
                                                                                        "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/bachata": ["sport", "suaps", "bachata",
                                                                           "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/danse-africaine": ["sport", "suaps", "danse africaine",
                                                                                   "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/danse-contemporaine": ["sport", "suaps",
                                                                                       "danse contemporaine",
                                                                                       "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/zumba": ["sport", "suaps", "zumba",
                                                                         "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/tango-argentin": ["sport", "suaps", "tango argentin",
                                                                                  "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/salsa": ["sport", "suaps", "salsa",
                                                                         "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/rocknroll": ["sport", "suaps", "rock'n'roll",
                                                                             "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/piloxing": ["sport", "suaps", "piloxing",
                                                                            "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/kizomba": ["sport", "suaps", "kizomba",
                                                                           "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/hip-hop": ["sport", "suaps", "hip-hop",
                                                                           "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/danse-orientale": ["sport", "suaps", "danse orientale",
                                                                                   "arts du mouvement"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/activites-nautiques": ["sport", "suaps",
                                                                                       "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/aquabike-aquagym-circuit-training": ["sport", "suaps",
                                                                                                     "aquabike",
                                                                                                     "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/plongee": ["sport", "suaps", "plongée",
                                                                           "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/natation-perfectionnement": ["sport", "suaps",
                                                                                             "natation",
                                                                                             "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/natation-intermediaire": ["sport", "suaps", "natation",
                                                                                          "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/natation-competition": ["sport", "suaps", "natation",
                                                                                        "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/natation-apprentissage": ["sport", "suaps", "natation",
                                                                                          "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/bnssa": ["sport", "suaps", "BNSSA",
                                                                         "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/baignade-libre": ["sport", "suaps", "baignade libre",
                                                                                  "activités nautiques"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/activite-detente": ["sport", "suaps",
                                                                                    "activité détente"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/yoga": ["sport", "suaps", "yoga", "activité détente"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/taichi-qi-gong": ["sport", "suaps", "taichi",
                                                                                  "activité détente"],
        "https://suaps.parisnanterre.fr/les-sports-et-activites/relaxation": ["sport", "suaps", "relaxation",
                                                                              "activité détente"],
        "https://ufr-lce.parisnanterre.fr/associations": ["association", "annuaire"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/dix-de-choeur": ["association",
                                                                                                          "musique"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/melodix": ["association",
                                                                                                    "musique"],
        "http://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/la-volt": ["association",
                                                                                                   "musique"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/revolte-toi-nanterre": [
            "association", "éloquence et débat"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/les-unis-verts": [
            "association", "écologie"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/mun-society-paris-nanterre": [
            "association", "éloquence et débat"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/acfa": ["association",
                                                                                                 "représentation étudiante"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/amnesty-international-groupe-jeunes-3047": [
            "association", "caritatif"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/faun": ["association",
                                                                                                 "représentation étudiante"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/association-psychologie-du-developpement": [
            "association", "médias, lecture et écriture"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/les-indifferents": [
            "association", "théâtre"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/les-impunis-ligue-dimprovisation": [
            "association", "théâtre"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/eloquentia-nanterre": [
            "association", "éloquence et débat"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/lysias": ["association",
                                                                                                   "éloquence et débat"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/lcc-production": [
            "association", "audiovisuel/cinéma"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/nuits-noires": ["association",
                                                                                                         "audiovisuel/cinéma"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/atelier-decriture": [
            "association", "médias, lecture et écriture"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/lili-blooms-book-club": [
            "association", "médias, lecture et écriture"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/pile-a-lire": ["association",
                                                                                                        "médias, lecture et écriture"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/rcva": ["association",
                                                                                                 "culture scientifique"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/altiski": ["association",
                                                                                                    "sport"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/cheerleading-paris-nanterre-1": [
            "association", "sport"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/laocho": ["association",
                                                                                                   "sport"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/la-nav-nanterre-association-de-voile": [
            "association", "sport"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/aumonerie-catholique-des-etudiant-es": [
            "association", "solidarité et entraide"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/asega": ["association",
                                                                                                  "solidarité et entraide"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/cercle-marxiste-de-nanterre": [
            "association", "citoyenneté"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/etudiants-musulmans-de-france-nanterre": [
            "association", "solidarité et entraide"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/ucph": ["association",
                                                                                                 "solidarité et entraide"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/union-etudiants-juifs-france-nanterre": [
            "association", "solidarité et entraide"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/lathena": ["association",
                                                                                                    "caritatif"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/antenne-jeunes-unicef-nanterre": [
            "association", "caritatif"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/amicale-des-etudiant-es-senegalais-es": [
            "association", "cultures du monde"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/compagnie-ptdr": [
            "association", "théâtre"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/paris-nanterre-maroc-1": [
            "association", "cultures du monde"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/le-poing-leve": ["association",
                                                                                                          "citoyenneté"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/union-etudiante-nanterre": [
            "association", "représentation étudiante"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/unef-nanterre": ["association",
                                                                                                          "représentation étudiante"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/ugen-fse": ["association",
                                                                                                     "représentation étudiante"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/promet": ["association",
                                                                                                   "association de filiere, ssa, sciences sociales et administrations"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/hypothemuse": ["association",
                                                                                                        "association de filiere, ssa, sciences sociales et administrations"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/gang": ["association",
                                                                                                 "association de filiere, ssa, sciences sociales et administrations"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/enape": ["association",
                                                                                                  "association de filiere, ssa, sciences sociales et administrations"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/bde-staps-rhinos": [
            "association", "sciences et techniques des activites physiques et sportives (staps)"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/psychx": ["association",
                                                                                                   "sciences psychologiques et sciences de l'éducation (spse)"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/comite-dactions-et-reseau-des-etudiants-en-sante-et-societe": [
            "association", "sciences psychologiques et sciences de l'éducation (spse)"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/les-alhumes": ["association",
                                                                                                        "sciences psychologiques et sciences de l'éducation (spse)"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/cine-rebelle": ["association",
                                                                                                         "philosophie, information-communication, langage, littérature, arts du spectacle (phillia)"],
        "https://aca2.parisnanterre.fr/associations/annuaire-des-associations-etudiantes/association-west-street": [
            "association", "sciences economiques, gestion, mathematiques, infomatique (segmi)"],
    }
    while True:
        question = input("\nVotre question (ou tapez 'exit' pour quitter) : ").strip()

        if question.lower() == 'exit':
            print("Au revoir !")
            break
            break

        # Trouver la réponse en fonction de la question
        response = asyncio.run(find_info_for_question(question, data, urls, cached_data))
        print(f"Réponse : {response}")


if __name__ == "__main__":
    main()