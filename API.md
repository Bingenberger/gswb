# API-Dokumentation

Alle API-Endpunkte sind per HTTP GET erreichbar und antworten mit JSON.  
Cross-Origin-Anfragen sind erlaubt (`Access-Control-Allow-Origin: *`), sodass die API direkt aus dem Browser einer anderen Website aufgerufen werden kann.

**Basis-URL (lokal):** `http://127.0.0.1:5005`

---

## GET /api/word/{lemma}

Gibt alle Daten zu einem Wort zurück.

### Parameter

| Parameter | Beschreibung |
|---|---|
| `lemma` | Das Wort in seiner Grundform, z.B. `Hund` oder `laufen` |

### Beispielaufruf

```
GET /api/word/Hund
```

### Antwort (200 OK)

```json
{
  "lemma": "Hund",
  "part_of_speech": "Nomen",
  "syllables": "Hund",
  "syllable_parts": ["Hund"],
  "definition": "Ein Hund ist ein Haustier, das ...",
  "example_sentence": "Der Hund bellt laut.",
  "spelling_strategy": "Das ist ein Nomen, darum schreiben wir es groß.",
  "spelling_categories": ["Verlängerungswort"],
  "translations": [
    { "language_code": "en", "translation": "dog" },
    { "language_code": "fr", "translation": "chien" },
    { "language_code": "tr", "translation": "köpek" },
    { "language_code": "ar", "translation": "كلب" }
  ],
  "relations": [
    { "relation_type": "word_family", "lemma": "Hündin" },
    { "relation_type": "synonym",     "lemma": "Vierbeiner" }
  ],
  "relations_grouped": {
    "word_family": ["Hündin"],
    "word_field":  [],
    "synonym":     ["Vierbeiner"]
  },
  "noun_forms": {
    "article": "der",
    "singular_form": "Hund",
    "plural_form": "Hunde",
    "nominativ_singular": "der Hund",
    "genitiv_singular":   "des Hundes",
    "dativ_singular":     "dem Hund",
    "akkusativ_singular": "den Hund",
    "nominativ_plural":   "die Hunde",
    "genitiv_plural":     "der Hunde",
    "dativ_plural":       "den Hunden",
    "akkusativ_plural":   "die Hunde"
  },
  "verb_forms": null,
  "adjective_forms": null,
  "word_family_boxes": [
    { "family_base": "Hund", "related_words": ["Hündin", "Hundehütte"] }
  ],
  "word_field_boxes": []
}
```

Die Felder `noun_forms`, `verb_forms` und `adjective_forms` sind jeweils nur für die passende Wortart befüllt, die anderen sind `null`.

### Fehlerantwort (404)

```json
{ "error": "not_found" }
```

---

## GET /api/autocomplete?q={suche}

Liefert Suchvorschläge zu einer Eingabe – geeignet für Live-Suchen und Suchfelder.

### Parameter

| Parameter | Beschreibung |
|---|---|
| `q` | Suchbegriff (Freitext, auch mit Tippfehlern) |

### Beispielaufruf

```
GET /api/autocomplete?q=Hun
```

### Antwort (200 OK)

```json
{
  "query": "Hun",
  "suggestions": [
    {
      "lemma": "Hund",
      "lemma_normalized": "hund",
      "part_of_speech": "Nomen",
      "match_type": "prefix",
      "score": null
    }
  ]
}
```

#### `match_type`-Werte

| Wert | Bedeutung |
|---|---|
| `exact` | Exakte Übereinstimmung |
| `prefix` | Eingabe ist Wortanfang |
| `fehlschreibung` | Bekannte Fehlschreibung dieses Wortes |
| `meintest-du` | Unscharfe Ähnlichkeit (Fuzzy-Match) |

---

## GET /api/words

Wortlisten für Leseübungen, z. B. Blitzlesen und Silbenrutsche der Grundschultafel.
Alle Filter sind optional und lassen sich kombinieren.

### Parameter

| Parameter | Beschreibung |
|---|---|
| `kategorie` | Rechtschreibkategorie, z. B. `Mitsprechwort`; mehrfach oder kommagetrennt (eine davon muss passen) |
| `wortart` | z. B. `Nomen`, `Verb`, `Adjektiv` |
| `silben` | genaue Silbenzahl; alternativ `silben_min` / `silben_max` |
| `buchstaben` | nur Wörter, die ausschließlich aus diesen Buchstaben bestehen, z. B. `maloi` (Groß-/Kleinschreibung egal) |
| `enthaelt` | Buchstabengruppe, die vorkommen muss, z. B. `au` |
| `max_laenge` | höchstens so viele Zeichen |
| `mit_bild`, `mit_ton` | `1` = nur Wörter, deren Bild- bzw. Tondatei tatsächlich vorhanden ist |
| `anzahl` | Anzahl der gelieferten Wörter (Standard 20, höchstens 200) |
| `zufall` | `1` = zufällige Auswahl statt alphabetisch |

### Beispielaufruf

```
GET /api/words?kategorie=Mitsprechwort&silben=2&mit_bild=1&zufall=1&anzahl=10
```

### Antwort (200 OK)

```json
{
  "total": 447,
  "words": [
    {
      "lemma": "Gabel",
      "syllables": ["Ga", "bel"],
      "part_of_speech": "Nomen",
      "spelling_categories": ["Mitsprechwort"],
      "image": "/static/images/Gabel.webp",
      "audio": "/static/audio/Gabel.mp3"
    }
  ]
}
```

`total` ist die Zahl aller Treffer, `words` enthält höchstens `anzahl` davon. `image` und
`audio` sind Pfade auf diesem Server oder `null`, wenn die Datei fehlt.

---

## GET /api/word-filters

Verfügbare Rechtschreibkategorien und Wortarten mit Anzahl, z. B. für Auswahlmenüs.

```json
{
  "categories": [{ "category": "Bausteinwort", "count": 2031 }],
  "parts_of_speech": [{ "part_of_speech": "Nomen", "count": 3120 }]
}
```

---

## JavaScript-Beispiel

```js
// Wortart abfragen
const res = await fetch("http://127.0.0.1:5005/api/word/Hund");
const word = await res.json();
if (res.ok) {
  console.log(word.part_of_speech);  // "Nomen"
  console.log(word.translations.find(t => t.language_code === "en").translation); // "dog"
}

// Suchvorschläge
const res2 = await fetch("http://127.0.0.1:5005/api/autocomplete?q=Hun");
const { suggestions } = await res2.json();
suggestions.forEach(s => console.log(s.lemma, s.match_type));
```
