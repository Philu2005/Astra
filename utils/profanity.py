import re
from typing import Dict, Any, List, Optional
from glin_profanity import Filter, SeverityLevel

# Profanity Filter initialisieren mit mehrsprachiger Kontext-Erkennung
profanity_filter = Filter({
    "all_languages": True,
    "enable_context_aware": True,
    "detect_leetspeak": True,
    "normalize_unicode": True
})

# =========================================================================
# WORTLISTEN & MUSTER
# =========================================================================

# 1. SCHWERE BELEIDIGUNGEN / HARD TRIGGERS (Hassrede & extreme Beleidigungen)
# WICHTIG: Ein Vorkommen dieser Begriffe führt NICHT mehr automatisch zu is_clear = True (ACTION)!
# Es dient als starkes Signal für die Einstufung. Ohne zielgerichteten Adressaten (z. B. bei "Ich bin ein Hurensohn"
# oder "Hurensohn-Move") darf KEINE automatische Bestrafung erfolgen, sondern maximal ein REVIEW.
HARD_TRIGGERS = [
    "hurensohn", "hurensoehne", "hurensöhne",
    "nigger", "nigga", "nuga",
    "bastard", "bastarde", "bastarden",
    "wichser", "wixxer", "wixer",
    "asshole", "assholes", "arschloch", "arschlöcher", "arschloecher",
    "fotze", "fotzen",
    "schlampe", "schlampen",
    "missgeburt", "missgeburten",
    "spast", "spasti", "spastis", "spasten"
]

# 2. WEITERE BELEIDIGUNGS-SUBSTANTIVE (z. B. für Plural- und Zusammensetzungserkennung)
STANDARD_INSULT_WORDS = [
    "idiot", "idioten", "vollidiot", "vollidioten",
    "depp", "deppen", "volldepp", "volldeppen",
    "penner", "pennern",
    "opfer",
    "hure", "huren",
    "bitch", "bitches", "cunt", "cunts", "dickhead", "dickheads"
]

ALL_KNOWN_INSULTS = set(HARD_TRIGGERS + STANDARD_INSULT_WORDS)

# Regex für alle bekannten Schimpfwörter
ALL_INSULTS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in ALL_KNOWN_INSULTS) + r")\b",
    re.IGNORECASE
)

HARD_TRIGGERS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in HARD_TRIGGERS) + r")\b",
    re.IGNORECASE
)

# 3. POSITIVER KONTEXT / KOMPLIMENTE (z. B. "Das ist fucking geil", "Du bist fucking cool")
# Fluchwörter wie "fucking" oder "verdammt" fungieren hier als positive Verstärker und sind keine Beleidigungen.
POSITIVE_CONTEXT_PATTERN = re.compile(
    r"\b(geil|geiler|geile|geiles|nice|nicer|awesome|gut|gute|guter|gutes|good|bester|beste|bestes|love|liebe|toll|tolle|toller|tolles|hammer|krass|krasse|krasser|krasses|stabil|stabile|stabiler|stabiles|king|ehrenmann|cool|cooler|cooles|legendär|legende)\b",
    re.IGNORECASE
)

# 4. REINE AUSRUFE / FILLER-FLUCHWÖRTER (z. B. "Fuck, ich hab...", "Oh shit", "Damn")
# Diese drücken Ärger/Überraschung über Situationen aus und zielen nicht auf Personen ab -> IGNORE.
EXCLAMATION_ONLY_PATTERN = re.compile(
    r"^(fuck|shit|damn|crap|verdammt|scheiße|scheisse|kacke|wtf|wth)([\s,!?.…]+.*)?$",
    re.IGNORECASE
)

# Wörter, die meistens nur als Ausruf oder Verstärker genutzt werden, sofern nicht direkt als Beleidigung konstruiert
MILD_FILLER_WORDS = {"fuck", "fucking", "shit", "damn", "crap", "verdammt", "scheiße", "scheisse", "kacke"}

# Wörter, die von mehrsprachigen Filtern fälschlicherweise als Schimpfwort erkannt werden (z. B. deutsches "nicht" oder "bitte")
COMMON_FALSE_POSITIVES = {"nicht", "bitte"}

# 5. ZUSAMMENGESETZTE BEGRIFFE / SACHBEZÜGE (z. B. "Hurensohn-Move", "Bastard-Aktion", "Scheiß-Wetter")
# Das Schimpfwort modifiziert eine Aktion/Sache und ist keine direkte Personenbeleidigung.
# Solche Sachbezüge werden vollständig ignoriert (IGNORE).
COMPOUND_MODIFIER_PATTERN = re.compile(
    r"(\b\w+[\-_]?(move|aktion|play|verhalten|art|game|tag|wetter|spiel|pass|ding|sache)\b|\b(was\s+für\s+ein[e]?|so\s+ein[e]?|echt\s+ein[e]?|das\s+war\s+(?:so\s+)?ein[e]?|ein[e]?)\s+\w+(?:[\s\-_]+)(move|aktion|play|verhalten|art|game|tag|wetter|spiel|pass|ding|sache)\b)",
    re.IGNORECASE
)

# 6. SELBSTBEZUG / SELBSTABWERTUNG (z. B. "Ich bin so ein Hurensohn", "Ich bin ein Bastard", "Was bin ich für ein Vollidiot")
# Aussagen über sich selbst sind keine zielgerichteten Beleidigungen gegen andere Personen und werden
# vollständig ignoriert (IGNORE), ohne ein Review-Ticket im Modlog auszulösen.
SELF_REFERENCE_PATTERN = re.compile(
    r"\b(ich\s+bin|ich\s+war|ich\s+wäre|bin\s+ich|ich\s+halt|ich\s+voll|ich\s+alter|ich\s+selbst|was\s+bin\s+ich|wie\s+dumm\s+bin\s+ich|ich\s+fühle\s+mich|ich\s+fuehle\s+mich|i\s+am|i'm|im\s+a|myself)\b|\bich\b\s+(?:(?:\w+)\s+){0,2}(?:" + "|".join(re.escape(w) for w in ALL_KNOWN_INSULTS) + r")\b",
    re.IGNORECASE
)

# 7. DIREKTE ANSPRACHE & ZIELGERICHTETE BELEIDIGUNG
# Pronomen für 2. Person (Gegenüber / Gruppe)
DIRECT_TARGET_PRONOUNS = re.compile(
    r"\b(du|dir|dich|dein|deine|deinem|deinen|deiner|deines|ihr|euch|euer|eure|eurem|euren|eures|eurer|you|u|ur|your|yours|yall|y'all)\b",
    re.IGNORECASE
)

# Direkte Beleidigungsmuster mit Näheprüfung (1 bis 5 Wörter zwischen Adressierung und Beleidigung)
DIRECT_INSULT_PROXIMITY_PATTERN = re.compile(
    r"\b(du|ihr|you|yall|y'all)\s+(?:(?:\w+)\s+){0,4}(" + "|".join(re.escape(w) for w in ALL_KNOWN_INSULTS) + r")\b",
    re.IGNORECASE
)

# Imperative Angriffe (z. B. "verpiss dich", "fick dich", "halt dein maul")
IMPERATIVE_ATTACK_PATTERN = re.compile(
    r"\b(verpiss\s+dich|fick\s+dich|halt['s\s]*(?:dein|deine|das|die)?\s*maul|halt\s+deine\s+fresse|fuck\s+you|fck\s+you|shut\s+the\s+fuck\s+up|stfu)\b",
    re.IGNORECASE
)

# Pronomen für Dritte (3. Person)
THIRD_PERSON_PRONOUNS = re.compile(
    r"\b(er|sie|es|ihn|ihm|ihnen|der|die|das|dieser|diese|dieses|diesem|diesen|dieser|he|she|they|him|her|them)\b",
    re.IGNORECASE
)


def _extract_profanities(content: str) -> tuple[bool, List[dict], List[str], dict]:
    """
    Findet Profanitäten mittels glin_profanity Filter sowie Hard-Trigger & Insult Heuristik.
    """
    res = profanity_filter.check_profanity(content)
    matches = [m for m in res.get("matches", []) if m.get("word", "").lower() not in COMMON_FALSE_POSITIVES]
    profane_words = [w for w in res.get("profane_words", []) if w.lower() not in COMMON_FALSE_POSITIVES]

    # Zusätzlich bekannte Schimpfwörter prüfen (z. B. falls glin_profanity Pluralformen wie 'Hurensöhne' oder 'Idioten' übersieht)
    for match in ALL_INSULTS_PATTERN.finditer(content):
        word = match.group(0)
        word_lower = word.lower()
        if word_lower not in COMMON_FALSE_POSITIVES and not any(w.lower() == word_lower for w in profane_words):
            profane_words.append(word)
            matches.append({
                "word": word,
                "index": match.start(),
                "severity": SeverityLevel.EXACT
            })

    # Auch imperative Beleidigungen (z. B. "verpiss dich", "halt dein maul") erfassen
    for match in IMPERATIVE_ATTACK_PATTERN.finditer(content):
        word = match.group(0)
        word_lower = word.lower()
        if word_lower not in COMMON_FALSE_POSITIVES and not any(w.lower() == word_lower for w in profane_words):
            profane_words.append(word)
            matches.append({
                "word": word,
                "index": match.start(),
                "severity": SeverityLevel.EXACT
            })

    contains_profanity = len(profane_words) > 0
    return contains_profanity, matches, profane_words, res


def check_profanity_message(content: str) -> Dict[str, Any]:
    """
    Prüft einen Nachrichtentext auf Schimpfwörter / Profanity und klassifiziert das Ergebnis
    unter Berücksichtigung des grammatikalischen Kontexts in 3 Kategorien:
    
    1. ACTION (is_clear = True, contains_profanity = True):
       Eindeutig direkt gegen eine Person oder Gruppe gerichtete Beleidigung (z. B. "Du bist ein Hurensohn", "Ihr seid Hurensöhne").
       Führt zur sofortigen Löschung und Verwarnung.
       
    2. REVIEW (is_clear = False, contains_profanity = True):
       Mehrdeutige Fälle oder Beleidigungen über Dritte (z. B. "Er ist ein Hurensohn", freistehende Schimpfwörter).
       Wird an das Moderationsteam zur Prüfung im Modlog weitergeleitet.
       
    3. IGNORE (contains_profanity = False, is_clear = False, outcome = "IGNORE"):
       Selbstbezug / Selbstabwertung ("Ich bin so ein Hurensohn", "Ich bin ein Bastard", "Was bin ich für ein Vollidiot"),
       Sachbezüge ("Hurensohn-Move", "Bastard-Aktion"), Komplimente mit Fluch-Verstärker ("fucking geil")
       oder situative Ausrufe ("Fuck, mein Handy...").
       Wird komplett ignoriert und erzeugt keinen Review-Eintrag.
    """
    if not content or not content.strip():
        return {
            "contains_profanity": False,
            "outcome": "IGNORE",
            "is_clear": False,
            "matches": [],
            "profane_words": [],
            "matched_words": "",
            "reason": "",
            "raw_result": {"contains_profanity": False, "profane_words": [], "matches": []}
        }

    contains_profanity, matches, profane_words, raw_res = _extract_profanities(content)
    if not contains_profanity:
        return {
            "contains_profanity": False,
            "outcome": "IGNORE",
            "is_clear": False,
            "matches": [],
            "profane_words": [],
            "matched_words": "",
            "reason": "",
            "raw_result": raw_res
        }

    matched_words = ", ".join(profane_words)
    reason = f"Beleidigungsfilter: {matched_words}"

    profane_words_lower = [w.lower() for w in profane_words]
    is_hard_trigger = any(
        any(ht in w for ht in HARD_TRIGGERS) or (w in HARD_TRIGGERS)
        for w in profane_words_lower
    )
    is_exact = any(m.get("severity") == SeverityLevel.EXACT for m in matches)

    # -------------------------------------------------------------
    # Kontext-Analyse
    # -------------------------------------------------------------
    has_positive = bool(POSITIVE_CONTEXT_PATTERN.search(content))
    has_self_ref = bool(SELF_REFERENCE_PATTERN.search(content))
    has_direct_target = bool(DIRECT_TARGET_PRONOUNS.search(content))
    has_compound = bool(COMPOUND_MODIFIER_PATTERN.search(content))
    
    # Prüfen, ob nur milde Füllwörter (z. B. "fuck", "shit") vorkommen
    is_only_mild = all(w in MILD_FILLER_WORDS for w in profane_words_lower)

    # -------------------------------------------------------------
    # DIREKTE ZIELGERICHTETE BELEIDIGUNG (ACTION-Kandidat)
    # -------------------------------------------------------------
    # Prüfen, ob eine direkte Ansprache mit Schimpfwort vorliegt
    is_direct_insult = False

    # 1. Direkte Näheprüfung: Pronomen der 2. Person gefolgt von Schimpfwort
    if DIRECT_INSULT_PROXIMITY_PATTERN.search(content):
        is_direct_insult = True

    # 2. Imperative Beleidigungen / Angriffe (z. B. "verpiss dich", "fick dich", "halt dein maul")
    if IMPERATIVE_ATTACK_PATTERN.search(content):
        is_direct_insult = True

    # WICHTIG: Selbstbezug und Sachbezug ausschließen!
    # Wenn Selbstbezug vorliegt ("Ich bin so ein Hurensohn", "Ich bin ein Bastard"),
    # darf dies NIEMALS als direkte Beleidigung (ACTION) gewertet werden.
    if has_self_ref:
        # Falls kein explizites "du" / "ihr" vorkommt, ist es eindeutig Selbstbezug
        if not bool(re.search(r"\b(du|ihr|you|yall|y'all)\b", content, re.IGNORECASE)):
            is_direct_insult = False

    # Wenn ein zusammengesetzter Sachbezug vorliegt ("Was für ein Hurensohn-Move"), keine direkte Personenbeleidigung
    if has_compound:
        is_direct_insult = False

    # -------------------------------------------------------------
    # ENTSCHEIDUNG FINDEN (ACTION vs IGNORE vs REVIEW)
    # -------------------------------------------------------------
    # 1. ACTION: Eindeutig direkt gegen jemanden gerichtet, exact match und kein positiver/relativierender Kontext
    if is_direct_insult and is_exact and not has_positive:
        return {
            "contains_profanity": True,
            "outcome": "ACTION",
            "is_clear": True,
            "matches": matches,
            "profane_words": profane_words,
            "matched_words": matched_words,
            "reason": reason,
            "raw_result": raw_res
        }

    # 2. IGNORE: Vollständiger Ausschluss für harmlose / nicht-personenbezogene Verwendungen:
    # - Positiver Kontext / Komplimente ("Das ist fucking geil", "Du bist fucking geil")
    # - Selbstbezug / Selbstabwertung ("Ich bin so ein Hurensohn", "Ich bin ein Bastard", "Was bin ich für ein Vollidiot")
    # - Sachbezüge / Modifikatoren von Aktionen ("Was für ein Hurensohn-Move", "Das war eine Bastard-Aktion")
    # - Situative Flüche / reine Ausrufe ("Fuck, ich hab mein Handy vergessen", "Oh shit")
    if has_positive or has_self_ref or has_compound or is_only_mild:
        return {
            "contains_profanity": False,
            "outcome": "IGNORE",
            "is_clear": False,
            "matches": matches,
            "profane_words": profane_words,
            "matched_words": matched_words,
            "reason": reason,
            "raw_result": raw_res
        }

    # 3. REVIEW: Verbleibende mehrdeutige Fälle (z. B. Beleidigungen über Dritte wie "Er ist ein Hurensohn",
    # oder freistehende Schimpfwörter ohne Kontext wie "Hurensohn!").
    # Diese erfordern eine manuelle Moderationsprüfung.
    return {
        "contains_profanity": True,
        "outcome": "REVIEW",
        "is_clear": False,
        "matches": matches,
        "profane_words": profane_words,
        "matched_words": matched_words,
        "reason": reason,
        "raw_result": raw_res
    }
