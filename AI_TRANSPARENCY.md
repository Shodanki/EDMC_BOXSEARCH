# Hinweis zur KI-Nutzung (Art. 50 KI-Verordnung) · AI disclosure (Art. 50 EU AI Act)

> **Hinweis zur KI-Nutzung:** SHBOXSEARCH wird mit Unterstützung eines
> KI-Systems entwickelt. Quellcode, Dokumentation und Release-Texte entstehen
> teilweise mit dem Sprachmodell-Assistenten **Claude** (Anthropic; seit 4.1.0
> über Claude Code mit dem Modell Claude Opus 5.5, bis 4.0 über Claude Pro).
> Jede Änderung wird vom Entwickler (CMDR Shodanki) geprüft, im Spiel getestet
> und unter eigener Verantwortung veröffentlicht. **Das Plugin selbst enthält
> kein KI-System:** Es arbeitet zur Laufzeit nur mit festen Regeln und
> Berechnungen, sendet keine Daten an KI-Dienste, und seine Ausgaben – Routen,
> Kandidaten, Statistiken, Exporte – sind nicht von einer KI erzeugt.

> **AI disclosure:** SHBOXSEARCH is developed with the help of an AI system.
> Source code, documentation and release texts are partly written with the
> language-model assistant **Claude** (Anthropic; Claude Code with Claude Opus
> 5.5 since 4.1.0, Claude Pro up to 4.0). Every change is reviewed by the
> developer (CMDR Shodanki), tested in the game and published under his own
> responsibility. **The plugin itself contains no AI system:** at run time it
> uses fixed rules and calculations only, sends no data to any AI service, and
> its output - routes, candidates, statistics, exports - is not AI-generated.

Maschinenlesbare Fassung / machine-readable: [`ai-disclosure.json`](ai-disclosure.json)

---

## 1. Einordnung (Stand der Prüfung: 04.11.2026)

Rechtsgrundlage: Verordnung (EU) 2024/1689 (KI-Verordnung). Art. 50 gilt seit
dem 2. August 2026; die Leitlinien der Kommission zu Art. 50 (C(2026) 5054)
liegen seit dem 20. Juli 2026 vor, der freiwillige Praxisleitfaden zu
KI-generierten Inhalten seit dem 10. Juni 2026.

| Frage | Ergebnis | Begründung |
|---|---|---|
| Ist SHBOXSEARCH ein KI-System (Art. 3 Nr. 1)? | **Nein** | Feste, vom Menschen festgelegte Regeln: Namens- und Boxel-Mathematik, Kepler-Bahnen, 2-opt-Routenoptimierung, Kurvenanpassung nach kleinsten Quadraten, Zählstatistik. Nach den Leitlinien der Kommission zur Definition von KI-Systemen fallen regelbasierte Datenverarbeitung, klassische mathematische Optimierung und einfache statistische Schätzung nicht darunter. |
| Pflicht nach Art. 50 Abs. 2 (maschinenlesbare Markierung synthetischer Inhalte)? | **Nicht bei uns** | Die Pflicht trifft den *Anbieter* des KI-Systems, das den Text erzeugt – hier Anthropic –, nicht den Nutzer des Assistenten. |
| Pflicht nach Art. 50 Abs. 4 UAbs. 2 (KI-Text, der die Öffentlichkeit über Angelegenheiten von öffentlichem Interesse informiert)? | **Nein** | Plugin-Dokumentation ist keine Information über Angelegenheiten von öffentlichem Interesse. Zusätzlich greift die Ausnahme für menschliche Überprüfung und redaktionelle Verantwortung. |
| Pflicht nach Art. 50 Abs. 1 (Hinweis bei Interaktion mit einem KI-System)? | **Nein** | Niemand interagiert mit einer KI, wenn er das Plugin benutzt. |
| Kennzeichnung trotzdem? | **Ja, freiwillig** | Transparenz gegenüber Nutzern, nach demselben Muster wie im Firmendossier (`ki_kennzeichnung.py`): sichtbar am Anfang, Rechtsgrundlage genannt, maschinenlesbar, Herkunftsnachweis. |

Keine Rechtsauskunft, sondern die dokumentierte Einschätzung des Entwicklers.

## 2. Umsetzung

| Baustein | Wo | Art. 50 Abs. 5 / ErwG 133 |
|---|---|---|
| Sichtbarer Hinweis **am Anfang**, deutsch und englisch, als Text | dieses Dokument, `README.md`, Release-Notizen ab 4.1.0 | „klar und eindeutig, spätestens bei der ersten Aussetzung“, barrierefrei (Text statt Symbol) |
| Maschinenlesbare Angaben | `ai-disclosure.json`: IPTC *Digital Source Type* `compositeWithTrainedAlgorithmicMedia` (Inhalt teils vom Menschen, teils mit KI), Rechtsgrundlage, Werkzeug, Modell, menschliche Prüfung, Prüfwert SHA-256 | Metadaten |
| Herkunftsnachweis je Änderung | Git-Commits ab 4.1.0 tragen `Co-Authored-By: Claude …`, sobald die KI beteiligt war; die Release-Notiz zu 4.0.0 nennt Claude Pro | Protokollierung |
| Laufzeit | kein KI-Aufruf, keine Übertragung von Spiel- oder Nutzerdaten an KI-Dienste; die Ausgaben des Plugins brauchen daher keine Kennzeichnung | – |

## 3. Was sich ändert, wenn KI zur Laufzeit dazukommt

Sollte SHBOXSEARCH künftig ein Sprachmodell oder ein anderes KI-System **zur
Laufzeit** nutzen, wird es zum KI-System, und der Entwickler wird Anbieter und
Betreiber im Sinne von Art. 3 Nr. 3 und 4. Dann gilt:

* Art. 50 Abs. 2: KI-erzeugte Inhalte in der Anzeige sichtbar **und**
  maschinenlesbar kennzeichnen, Modell und Stand protokollieren.
* Art. 50 Abs. 1: Hinweis, sobald man mit einer KI-Funktion interagiert.
* Spieldaten an einen KI-Dienst nur nach ausdrücklicher Einwilligung in den
  Einstellungen, standardmäßig aus.
* Dieses Dokument und `ai-disclosure.json` werden vor dem Release ergänzt.

## 4. Textbausteine

**Fußzeile für Release-Notizen (EN):**
> AI disclosure (Art. 50 EU AI Act): developed with the help of the AI
> assistant Claude (Anthropic); every change reviewed and tested by the
> developer. The plugin contains no AI system and its output is not
> AI-generated. Details: AI_TRANSPARENCY.md

**Fußzeile für Release-Notizen (DE):**
> Hinweis zur KI-Nutzung (Art. 50 KI-Verordnung): entwickelt mit Unterstützung
> des KI-Assistenten Claude (Anthropic); jede Änderung vom Entwickler geprüft
> und getestet. Das Plugin enthält kein KI-System, seine Ausgaben sind nicht
> KI-erzeugt. Details: AI_TRANSPARENCY.md

**Forum-/Discord-Beitrag (EN, kurz):**
> SHBOXSEARCH is built with AI assistance (Claude, Anthropic) and reviewed by
> me. No AI runs inside the plugin and none of your data goes to an AI service.

## Quellen

* VO (EU) 2024/1689, Art. 3, 50, 113 – <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
* Überblick Art. 50: <https://artificialintelligenceact.eu/transparency-rules-article-50/>
* Leitlinien C(2026) 5054: <https://www.williamfry.com/knowledge/time-running-out-as-ai-transparency-guidelines-published/>
* Vorbereitung auf den 2. 8. 2026: <https://datamatters.sidley.com/2026/06/24/eu-ai-act-transparency-obligations-preparing-for-compliance-by-2-august-2026/>
* IPTC Digital Source Type: <http://cv.iptc.org/newscodes/digitalsourcetype/>
