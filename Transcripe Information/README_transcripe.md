# Transcribe

Streamlit-App zur Audio-Transkription mit Gemini oder Voxtral und zum
satzorientierten SRT-Export.

## Start

Abhängigkeiten aus `requirements.txt` installieren und `streamlit run app.py`
ausführen. API-Schlüssel werden aus `.env` geladen:
`GEMINI_API_KEY` für Gemini, `MISTRAL_API_KEY` für Mistral.

Für YouTube-Abrufe ist zusätzlich **Deno ab Version 2.3** erforderlich.
Unter Windows lässt es sich mit
`winget install --id DenoLand.Deno --exact --source winget --scope user`
installieren. Die App findet Deno über `PATH` oder den benutzerspezifischen
WinGet-Alias bzw. Standard-Paketordner. Bei anderen Installationswegen nach einer PATH-Änderung die App
neu starten. `requirements.txt` enthält `yt-dlp[default]`, damit die passenden
JavaScript-Challenge-Skripte (`yt-dlp-ejs`) mitinstalliert und aktualisiert
werden. Diese Konfiguration gilt für Metadaten, Untertitel, Audio und Video.

## Lokale Übergabe an SubTranslate-2

Nach erfolgreichem Export wird im Auftragsordner zuletzt atomar
`<basis>.ready.json` geschrieben. Nur dieses Manifest ist ein Fertigsignal;
SRT und Wortdaten können schon während der Verarbeitung vorhanden sein.
Jeder neue Verarbeitungslauf erhält eine UUID als `export_id`. Alte Fertig-
und Medienmarker derselben Dateibasis werden vor Änderungen entfernt.

Das Manifest enthält `version: 1`, `export_id`, relative Pfade für `srt`,
`words`, `metadata`, `words_original`, `words_review` und `audio` sowie
`sha256` als Objekt mit SHA-256-Prüfsummen nach denselben Feldnamen.
Optionale, im aktuellen Lauf nicht erzeugte Dateien sind `null` und haben
keine Prüfsumme. Alte Prüfdateien werden nicht automatisch mit übergeben.
Extern ausgewähltes Audio beim Wortdaten-Reexport wird dafür in `.media`
kopiert. Die Pfade beziehen sich auf den Manifest-/Auftragsordner, unter
Windows mit Backslashes.

Der optionale Video-Download blockiert den Fertigmarker nicht. Sobald sowohl
das Transkript exportiert als auch das Video fertig ist, schreibt die App
separat `<basis>.media.json` mit `version: 1`, derselben `export_id`, dem
relativen `video`-Pfad und `sha256.video`. Das funktioniert auch, wenn das Video
vor dem Transkript fertig wurde. Fehler bei dieser Medienmeldung erscheinen
separat in der Oberfläche; der fertige Transkriptionsexport bleibt erhalten.
Die App muss bis zum Videoabschluss weiterlaufen. Alte Hintergrundaufträge
dürfen nach einem erneuten Export keinen Marker für die neue Export-ID erzeugen.

SubTranslate-2 überwacht beide Markerdateien, kopiert die genannten Dateien ins
eigene Projekt und prüft die Prüfsummen der Kopien, bevor es den Import bestätigt.
So werden Überschreibungen während des Imports erkannt. `export_id` persistent
speichern und wiederholte Dateisystemereignisse deduplizieren. Für eine vor dem
Projektimport eintreffende Medienmeldung deren Export-ID vormerken.
Mehrere gleichzeitig schreibende Sitzungen mit derselben Dateibasis sind
weiterhin nicht unterstützt; Prüfsummen ersetzen keine Schreibsperre.

## Oberfläche und Standardwerte

Die Oberfläche hat zwei Tabs: **Transkription** für Quelle, Dateiname,
Prüf-Checkbox, Verarbeitung und Downloads; **Einstellungen** für Modelle,
Sprachhinweis, Untertitelparameter, Ausgabeordner und Video-Download.
**Einstellungen ändern** wechselt direkt zum Einstellungs-Tab.
Nach erfolgreichem Export entfällt der Start-/Fortsetzen-Button für diesen
Auftrag. Bei Bedarf lässt sich unter **Abgeschlossenen Auftrag erneut
verarbeiten** ausdrücklich **Untertitel erneut erstellen** wählen, etwa nach
einer Änderung der Einstellungen. Passende Zwischenstände werden dabei
wiederverwendet; eine aktivierte Transkriptprüfung wird erneut ausgeführt.
Für eine andere Quelle steht die normale Start-/Fortsetzen-Aktion bereit.
Die Transkriptprüfung ist ab Werk aktiviert; die zusätzliche sprachliche
LLM-Gruppierung steht unter **Zusatzoptionen** und ist ab Werk deaktiviert.
Die beiden Funktionen sind unabhängig voneinander.

Änderungen im Einstellungs-Tab sind zunächst Entwürfe.
**Für nächsten Auftrag übernehmen** verwendet sie in dieser Sitzung, ohne
gespeicherte Standardwerte zu verändern. **Als Standard speichern** übernimmt
sie zusätzlich dauerhaft für die gesamte App-Installation, auch nach einem
Neustart. Dabei wird auch die Prüf-Checkbox aus dem Haupttab gespeichert.
**Gespeicherte Standardwerte laden** lädt sie zunächst in den Entwurf;
anschließend übernehmen. **Auf Werkseinstellungen zurücksetzen** ersetzt nach
Bestätigung die gespeicherten und aktiven Werte. Der Werks-Ausgabeordner ist
das Arbeitsverzeichnis der App.

Die Datei `.frontend_defaults.json` im Arbeitsverzeichnis enthält ausschließlich
validierte Einstellungen, keine API-Schlüssel, und ist von Git ausgeschlossen.
Unlesbare oder ungültige Standardwerte werden als Fehler angezeigt, nicht still
durch Werkseinstellungen ersetzt. Ausgabe- und aktivierte Video-Zielordner müssen
beim Übernehmen existieren. Ordner beziehen sich auf den App-Rechner, nicht
automatisch auf den Browser-Rechner. Offene Prüfungen behalten die beim Start
übernommenen Einstellungen.

Für Mistral/Voxtral kann die Spracherkennung automatisch erfolgen oder optional
mit einem einzelnen Sprachhinweis auf Deutsch, Englisch, Französisch oder
Spanisch ausgeführt werden. Der Hinweis verbessert gegebenenfalls die Erkennung,
ist aber kein Sprachfilter und trennt keine gleichzeitig sprechenden Stimmen.
Die Spracheinstellung erzeugt einen eigenen Transkriptionscache.
Ungültige Zeitstempel in gespeicherten Audioabschnitten werden beim Fortsetzen
erkannt; betroffene Abschnitte werden neu transkribiert, gültige Checkpoints
bleiben erhalten. Scheitert ein Mistral-Abschnitt erneut an der Zeitfolge,
kann dieser Abschnitt ausdrücklich in 60-Sekunden-Teilen neu transkribiert
werden. Diese Reparatur-Teilstücke werden als Mono-PCM-WAV erzeugt, um
Dekodierungsprobleme mit segmentierten MP3-Dateien zu vermeiden. Sie werden nur
bei gültiger Gesamtzeitfolge als Checkpoint gespeichert; dadurch entstehen
zusätzliche Mistral-Aufrufe.

Im Audiomodus öffnet sich der Dateidialog ohne Dateitypfilter, um fehlerhafte
MIME-Zuordnungen auf Mobilgeräten nicht als Auswahlblockade zu übernehmen.
Die App prüft anschließend die Endung (MP3, WAV, M4A, OGG oder FLAC, unabhängig
von Groß-/Kleinschreibung). FFmpeg prüft bei der Audioaufbereitung, ob der Inhalt
decodierbar ist. Im Wortdatenmodus bleibt der JSON-Dateifilter aktiv.

### Alternativer mobiler Upload

Falls nach der Dateiauswahl auf Android/Chrome oder über Codespaces nichts
erscheint, **Alternativer mobiler Upload (bis 20 MB)** einschalten. Dieser
zusätzliche Weg ist für Audio und Wortdaten-JSON verfügbar. Er verwendet eine
native Browser-Dateiauswahl ohne MIME-Filter, liest die Datei im Browser und
überträgt sie über die bestehende Streamlit-Komponentenverbindung. Der normale
Upload-Endpunkt und dessen Drag-and-drop-Dateiauswahl werden dabei nicht
verwendet. Es werden keine externen Dienste oder Bibliotheken eingebunden;
die Zugriffsschutz-Einstellungen bleiben unverändert.

Dateiname und Lesestatus erscheinen direkt in der Dateiauswahl. Erst
**Upload angekommen** in der App bestätigt den Empfang auf dem Server.
Lesefehler, leere Dateien, unzulässige Endungen, Größenüberschreitungen und
ausbleibende Bestätigung werden angezeigt. Beide Seiten prüfen die 20-MB-Grenze;
die Übertragung ist Base64-kodiert und benötigt zusätzlichen Speicher.
Für größere Dateien den Standard-Upload verwenden. Das ist ein alternativer
Übertragungsweg, keine nachgewiesene Behebung der bislang nicht auf einem
Android-Gerät reproduzierten Ursache des Standard-Upload-Problems.

## YouTube-Audio transkribieren

Im Eingabemodus **YouTube-Video transkribieren** eine unterstützte HTTPS-URL
zu einem einzelnen öffentlichen Video einfügen. Nach Übernahme der Eingabe
(Enter oder Verlassen des Feldes) lädt die App automatisch die Informationen
und zeigt währenddessen einen Spinner; ein Bestätigungsbutton entfällt.
Erfolgreiche Prüfungen werden innerhalb der Sitzung für dieselbe Quelle
wiederverwendet. Schlägt die Prüfung fehl, wird der Fehler angezeigt und die
Transkription bleibt gesperrt; beim nächsten App-Durchlauf wird erneut geprüft.
Vor der Transkription zeigt die App Titel,
Kanalname, Beschreibung und ausschließlich manuell hinterlegte Untertitelsprachen.
Automatisch erzeugte Untertitel werden nicht als verfügbare Downloadspur angeboten.
Eine manuelle Spur kann im Originalformat heruntergeladen werden; ein Download ist
optional und unabhängig von der Audio-Transkription. Playlist-, Live-, Anmelde-
und private Inhalte werden nicht unterstützt. Videos sind auf 3 Stunden und
Audiodownloads auf 1 GiB begrenzt.

Jeder Auftrag wird in einem Unterordner des konfigurierten Ausgabeordners abgelegt.
YouTube-Aufträge verwenden den bereinigten Videotitel und die Video-ID, Uploads
den Dateinamen. SRT-Datei, zugehörige YouTube-Metadaten-JSON, Wortdaten, herunter-
geladene Audios, optionale Videos, manuelle Untertitel und Transkriptionscache
bleiben in diesem Auftragsordner. YouTube-Dateien verwenden standardmäßig
denselben bereinigten Videotitel als Dateibasis: MP3-Audio, SRT, optionales
MKV-Video und manuelle Untertitel im Originalformat. Die gemeinsame Dateibasis
kann im Haupttab angepasst werden. Wenn mehrere manuelle Untertitelsprachen
heruntergeladen werden, wird zur Unterscheidung der Sprachcode angefügt. Bei
Audio-Uploads wird der SRT-Dateiname aus dem Uploadnamen vorbelegt und kann
separat angepasst werden. Ältere Transkriptionszwischenstände werden beim
nächsten passenden Auftrag in den neuen Auftragsordner kopiert.

Nur Inhalte herunterladen und verarbeiten, für die die nötigen Rechte bestehen.
Die Funktion umgeht keine Anmeldungen oder Zugriffsbeschränkungen. In
`media_sources.py` sind Eingabe und Resolver vom Transkriptionsablauf getrennt.
Im Tab **Einstellungen** kann zusätzlich ein unabhängiger Video-Download
aktiviert und die maximale Auflösung gewählt werden:
480p, 720p, 1080p oder beste verfügbare Qualität. Falls die gewünschte Auflösung
fehlt, wird die beste niedrigere verwendet. Video und Ton werden ohne
Neukodierung in einer MKV-Datei zusammengeführt und direkt neben der SRT-Datei
im Auftragsordner gespeichert. Das ist unabhängig vom MP3-Abruf für die Transkription; die
Audiospur kann daher zweimal übertragen werden. Videos haben das 3-Stunden-Limit,
aber kein 1-GiB-Audiolimit und können entsprechend viel Speicher benötigen.

`youtube_video.py` übernimmt Abruf und Hintergrundjob, ohne Streamlit-Aufrufe
aus dem Download-Thread. Ein paralleles Streamlit-Fragment aktualisiert die
Anzeige alle 0,5 Sekunden, auch während Audioabruf und Transkription.
Der Fortschrittsbalken bezieht sich jeweils auf die aktuelle Spur (Video oder
Audio), nicht auf den Gesamtauftrag. Bei unbekannter Größe und während der
Zusammenführung wird stattdessen der aktuelle Verarbeitungsschritt angezeigt. Video-Fehler
stoppen nicht die Transkription und werden separat angezeigt. Pro Sitzung
läuft höchstens ein Video-Download. Die App muss bis zum Abschluss laufen;
ein Beenden der App kann den Download unterbrechen. Bereits vollständige
Videos werden anhand eines Abschlussmanifests wiederverwendet.

Jeder tatsächliche Video-Abruf ergänzt ein UTC-datiertes Diagnoseprotokoll
`video-download.log` im internen Downloadordner unter `.media\video`.
Es enthält die Video-ID, Qualität, yt-dlp-Version, ausgewählten Format-IDs,
Abrufwarnungen und Fehler. Format-IDs werden bereits vor der Übertragung
protokolliert, auch wenn diese mit HTTP 403 scheitert. URLs werden entfernt;
ausführliche Debugausgaben, HTTP-Header und Cookies werden nicht protokolliert.
Bei einem Abruffehler zeigt die App auch den Protokollpfad an. Ein Cache-Treffer
startet keinen neuen Abruf und erzeugt keinen neuen Protokolleintrag.

Video-Downloads verwenden kurze interne Ordnerkennungen und die Video-ID für
temporäre Dateien unter `.media/video/`, damit lange Titel die Windows-Pfadgrenze
nicht überschreiten. Erst nach Download und Zusammenführung wird die fertige
MKV-Datei mit dem gemeinsamen Dateinamen direkt in den Auftragsordner verschoben.
Lange finale Dateipfade werden dabei unter
Windows über die Langpfad-Schnittstelle gespeichert. Bereits abgeschlossene
Videos in der älteren titelbasierten Ordnerstruktur werden beim nächsten
passenden Download ohne erneuten Abruf in den Auftragsordner verschoben.
Ist schon der Ausgabeordner zu tief verschachtelt für die internen Downloadpfade,
zeigt die App eine ausdrückliche Aufforderung zur Wahl eines kürzeren Pfads.

Der Ausgabeordner liegt auf dem **Streamlit-Rechner**, nicht automatisch auf dem
Rechner des Browsers. Bei lokalem Windows-Betrieb ist das die lokale Festplatte;
in Codespaces bleibt es das Codespaces-Dateisystem. Das Löschen der
Transkriptionszwischenstände entfernt nur den Cache des Auftrags; die Mediendateien
und Exporte im Auftragsordner bleiben erhalten.

YouTube kann auch den Abruf öffentlicher Videos mit einer Bot-Prüfung blockieren.
Die Meldung „Sign in to confirm you're not a bot“ wird ausdrücklich als
Zugriffshürde angezeigt; die Transkription startet dann nicht. Ein erneuter
Start garantiert keinen erfolgreichen Abruf. Browser-Cookies, Anmeldungen
und das Umgehen dieser Prüfung sind nicht Teil der Funktion. Als Alternative
kann eine bereits vorhandene oder aus einer erlaubten Quelle bezogene
Audiodatei über **Audio transkribieren** verarbeitet werden.

## Untertitel und Lesezeit

Der Export bevorzugt vollständige Sätze statt starrer Zeichen-Schnitte. Kurze
abgeschlossene Sätze können zusammengefasst werden. Lange Sätze werden bevorzugt
an Satzteilgrenzen oder Sprechpausen geteilt. Ohne LLM basiert die Erkennung auf
Satzzeichen und Pausen; sie ist keine vollständige grammatikalische Analyse.
Zahlpunkte vor Monatsnamen und erkannten Ordnungszahl-Fortsetzungen (z. B.
„18. September“, „21. Jahrhundert“ oder „2. wichtige Frage“) gelten nicht als
Satzende. Diese Wortpaare bleiben auch bei Längen-Schnitten und LLM-Batchgrenzen
zusammen; entsprechende LLM-Schnittvorschläge werden abgelehnt. Ein Satzende
wie „Das war 2026. Danach …“ bleibt dagegen erhalten.

In der Oberfläche einstellbar:

- Zeichen-Zielwert (Standard: 80) und Zeichen-Obergrenze (120).
- Maximale Anzeigedauer (8 Sekunden).
- Gewünschte Lesegeschwindigkeit (18 Zeichen/Sekunde).
- Maximaler Nachlauf in Pausen (2 Sekunden).
- Gewünschter Abstand zum nächsten Untertitel (80 Millisekunden).

Satzenden haben Vorrang vor dem Zeichen-Zielwert, nicht vor den Obergrenzen.
Zusätzliche Lesezeit wird nur bei Bedarf genutzt und überschreitet weder den
Nachlauf noch die maximale Dauer oder den Beginn des nächsten Untertitels.
Gesprochene Wörter werden für den gewünschten Abstand nicht vorzeitig
ausgeblendet. Unvermeidbare Überschreitungen der Zeichen- oder Dauerobergrenze
durch ein einzelnes Wort werden angezeigt. Die Lesegeschwindigkeit dient
weiterhin zur Berechnung zusätzlicher Anzeigedauer; Hinweise bei überschrittener
Lesegeschwindigkeit werden nicht ausgegeben. Untrennbare
Zahl-Wort-Paare, die selbst eine Obergrenze überschreiten, bleiben zusammen und
erzeugen einen Hinweis. Überlappende Wortzeiten an einer Untertitelgrenze
führen zum Zusammenführen der betroffenen Gruppen mit sichtbarem Hinweis
auf Wort-ID und Überlappungsdauer. Dies gilt für regelbasierte und
LLM-Gruppierung sowie Zwischen-SRTs. Worttext und Wortzeiten werden nicht
gekürzt, verschoben oder gelöscht. Durch Zusammenführen unvermeidbare
Zeichen-/Dauerüberschreitungen werden ebenfalls gemeldet. Nicht endliche, negative und Wort-intern rückwärts laufende Zeitstempel bleiben
Fehler. Begrenzte Rückwärtsläufe von höchstens zwei Sekunden gegenüber dem
bisher höchsten Wortbeginn werden als Zeitstempel-Auffälligkeit an die optionale
Transkriptprüfung übergeben. Das LLM erhält die betroffenen IDs und Zeitwerte,
hört aber kein Audio. Die App verlangt die Bestätigung des Gegenhörens und
bündelt den bestätigten Wortbereich für den Export zu einem Eintrag mit dem
frühesten Wortbeginn und spätesten Wortende; Einzelwortzeiten werden nicht
geschätzt.

## Optionale LLM-Gruppierung

Verfügbare Voreinstellungen:

| Modell | API-ID |
| --- | --- |
| Gemini 3.1 Flash Lite | `gemini-3.1-flash-lite` |
| Gemini 3.5 Flash Lite | `gemini-3.5-flash-lite` |
| Gemini 3.1 Pro Preview | `gemini-3.1-pro-preview` |
| Mistral Small | `mistral-small-latest` |
| Mistral Medium | `mistral-medium-latest` |
| Mistral Large | `mistral-large-latest` |

Die API-ID lässt sich je Modell anpassen. Die Mistral-`latest`-Aliase folgen
Anbieterupdates; Zugriff und Verfügbarkeit hängen vom API-Konto ab.
Transkription und Gruppierung dürfen unterschiedliche Anbieter verwenden.
Die Gruppierung sendet Transkripttext und Wortzeiten an den gewählten Anbieter
und verursacht zusätzliche API-Kosten. Sie ist standardmäßig ausgeschaltet.

Das LLM gibt ausschließlich aufsteigende Wort-End-IDs zurück. Der Code validiert
Schema, vollständige Abdeckung und Obergrenzen und übernimmt Text und Zeiten aus
den Originaldaten. Ungültige Antworten werden nicht still durch einen
unkorrigierten Export ersetzt.
Vollständige, anhand der Satzzeichen erkannte Sätze innerhalb der Zeichen- und
Dauerobergrenzen bleiben zusammen; der Zeichen-Zielwert allein erlaubt keine
Teilung. Nach der Validierung entfernt der Code unnötige interne LLM-Schnitte
in solchen Sätzen und setzt bei Bedarf deren äußere Grenzen. Dies gilt auch
über LLM-Batches hinweg. Sinnvolle LLM-Schnitte in zu langen Sätzen bleiben
erhalten. Unvollständige Transkriptenden werden nicht als vollständige Sätze
behandelt. Text und Wortzeiten bleiben dabei unverändert.
Bei ungültiger Ausgabe erfolgen höchstens zwei zusätzliche Korrekturaufrufe pro
Batch mit konkretem Validierungsfehler und vorheriger Antwort. Diese Versuche
werden sichtbar angezeigt und können zusätzliche API-Kosten verursachen.
Nach insgesamt drei ungültigen Antworten bricht der Export mit Angabe des
betroffenen Wortbereichs ab. IDs werden weder automatisch sortiert noch
umgedeutet. Nur vollständig validierte Antworten werden zwischengespeichert;
ungültige alte Cache-Einträge werden mit Hinweis neu angefordert. API- und
Transportfehler werden durch diese Ausgabe-Korrekturschleife nicht wiederholt.

Nach drei ungültigen Gruppierungsantworten kann ausdrücklich über
**Ohne LLM-Gruppierung regelbasiert exportieren** fortgefahren werden.
Das ist kein automatischer Ersatz für eine erfolgreiche LLM-Gruppierung:
Die Oberfläche kennzeichnet den Export als regelbasiert. Verwendet werden
die aktuellen Wortdaten einschließlich bereits freigegebener Textkorrekturen
und die gespeicherten Zeichen-/Dauer-/Lesezeiteinstellungen. Originalwortdaten
und Prüfentscheidungen bleiben erhalten. Die Gruppierungsfehler bleiben bis
zur Entscheidung sichtbar; es werden keine zusätzlichen LLM-Aufrufe für den
regelbasierten Export gemacht.

Aufrufe verarbeiten ungefähr 250 Wörter mit Kontext auf beiden Seiten und
bevorzugen nahe Satzenden als Batchgrenzen. Bei außergewöhnlich langen Sätzen
ohne erkannte Satzenden kann eine Batchgrenze dennoch innerhalb eines Satzes
liegen. Eine fremde Übersetzungs-App kann weiterhin selbst ungünstige Batches
bilden; die SRT enthält keine verbindlichen Übersetzungs-Batchgrenzen.

## Optionale Transkriptprüfung mit Freigabe

Die zusätzliche Checkbox zur Transkriptprüfung nutzt das ausgewählte LLM
unabhängig von der Gruppierungsoption. Sie sendet Text mit Sprachwechseln,
aber kein Audio, in Batches von 250 Worteinheiten mit Nachbarkontext.
Zusätzliche API-Kosten entstehen. Die Prüfung übersetzt nicht und soll weder
gesprochenen Stil glätten noch Tatsachen nach Weltwissen umschreiben.
Der gemeinsame Prüfauftrag für Gemini und Mistral priorisiert wenige begründete
Erkennungsfehler statt allgemeiner Sprachkritik. Worteinheiten werden im
Satzkontext und in ihrer Originalsprache beurteilt. Bloße Synonyme, alternative
Satzzeichen und historisch vermeintlich unplausible Jahreszahlen sind kein
Grund für eine Meldung. Beispiele erläutern korrekte deutsche/französische
Formulierungen und einen möglichen beschädigten Satz mit Audio-Prüfbedarf.
Diese Promptregeln sind keine Garantie für fehlerfreie Modellvorschläge.

Die Oberfläche zeigt Original, Vorschlag, Begründung, Kategorie,
modellgeschätzte Sicherheit und Audio-Prüfbedarf. Zusätzlich zeigt sie den
vollständigen Untertitel, in dem der markierte Bereich liegt, und erlaubt die
Bearbeitung des ganzen Untertitels. Eine Änderung dort ersetzt die
Einzelvorschläge innerhalb dieses Untertitels; sein Text wird als eine Einheit
mit dem gesamten ursprünglichen Zeitbereich gespeichert. Die Vorschau nutzt
die ausgewählte LLM-Gruppierung oder, falls diese nicht verfügbar ist, eine
sichtbar gekennzeichnete regelbasierte Vorschau. Nach einer Textänderung werden
die Untertitelgrenzen beim Export erneut berechnet.
Jeder Vorschlag erhält bei
vorhandener Audioquelle einen Player mit dem betroffenen Wortbereich und
jeweils zwei Sekunden Kontext davor und danach, begrenzt durch Dateianfang
und -ende. FFmpeg liest die gespeicherte Originaldatei und erzeugt einen kurzen
WAV-Ausschnitt; nur dieser Ausschnitt wird an den Browser geliefert. Die
Originaldatei bleibt unverändert, es wird kein zusätzlicher Audio-API-Aufruf
ausgeführt. Bei Audio-Uploads wird für die Prüfung eine lokale Kopie im
Job-Cache behalten; diese ist anders als das YouTube-Archiv löschbar.
Fehlende Dateien oder ungültige Audioausschnitte werden sichtbar gemeldet.
Korrekturen erscheinen automatisch in einem verpflichtenden Dialog, der
nicht per Escape oder Klick außerhalb geschlossen werden kann. Pro Schritt
wird eine Auffälligkeit mit einem direkt editierbaren vollständigen Untertitel
angezeigt. **Vorschlag annehmen** ersetzt die markierte Stelle im Textfeld,
ohne bereits zu speichern oder zu exportieren. Bereits manuell bearbeitete
Nachbartexte bleiben erhalten; ist die Originalstelle nicht mehr eindeutig,
wird ein Fehler angezeigt und die Änderung muss direkt eingetragen werden.
**Bestätigen** speichert den aktuellen Untertiteltext und führt zur nächsten
Auffälligkeit. Für unveränderten Text reicht ebenfalls **Bestätigen**.
Bei mehreren Auffälligkeiten im selben Untertitel bleiben die Änderungen
erhalten. Die letzte Bestätigung exportiert alle Freigaben.
**Auftrag abbrechen – nicht exportieren** erlaubt einen bewussten Abbruch.
Eine erfolgreiche Prüfung ohne Auffälligkeiten exportiert direkt.
Offene Vorschläge bleiben in derselben Sitzung bei Neuausführungen erhalten;
eine neue Verarbeitung ist bis zur Freigabe oder zum Abbruch gesperrt.
Während einer aktivierten Prüfung wird keine ungeprüfte Zwischen-SRT geschrieben.
Fehlgeschlagene Prüfungen und Gruppierungen verlangen ebenfalls eine bewusste
Entscheidung im Dialog; Zwischenstände werden nur nach Bestätigung gelöscht.

Schema, Zielbereich, exakter Originaltext und überlappende Vorschläge werden
validiert. Fehler brechen die Prüfung sichtbar ab, ohne automatische
Textkorrektur. Die Audio-Kennzeichnung ist keine Verifikation: Das Modell hört
kein Audio und auch eine hohe Sicherheit ersetzt das Gegenhören nicht.
Bei ungültigen Prüfantworten gibt die Oberfläche den konkreten Wortbereich
und bei abweichendem Original den erwarteten sowie gelieferten Text an.
Das Modell bekommt dieses Fehlerfeedback für höchstens zwei zusätzliche
Korrekturaufrufe pro Batch (zusätzliche API-Kosten). Nach drei ungültigen
Antworten bricht die Prüfung ab. Ausschließlich äußere Leerraumzeichen im
Originalzitat werden beim Vergleich ignoriert; nach erfolgreichem Vergleich
stammt das angezeigte und gespeicherte Original aus den Eingabewörtern.
Innere Abstände, Wortlaut, Großschreibung, Satzzeichen und Wort-IDs bleiben
streng geprüft. Vorschläge werden nicht auf andere Wortstellen verschoben.
API-/Transportfehler werden nicht durch diese Korrekturschleife wiederholt.

Bei abweichendem Original erhält das Modell zusätzlich strukturiertes Feedback
mit dem erwarteten Originalzitat und benachbarten Wort-IDs. Führende/äußere
Leerzeichen der Eingabe-Worteinheiten werden im Prüf-Payload entsprechend der
Originalvergleichsregel entfernt; gespeicherte Wortdaten bleiben unverändert.
Das Modell muss IDs aus dem `id`-Feld verwenden, nicht Arraypositionen oder
selbst gezählte Wörter. Dies garantiert keine gültige Modellantwort.
Nach drei ungültigen Antworten bietet die Oberfläche ausdrücklich
**Ohne Transkriptprüfung mit Originalwortdaten exportieren** an. Erst dieser
Klick exportiert die unveränderten Wortdaten mit den gespeicherten
Gruppierungseinstellungen; der Export wird als ohne erfolgreiche Prüfung
gekennzeichnet. Ungültige Vorschläge werden nicht übernommen. Der Fehlerzustand
bleibt in derselben Sitzung über Neuausführungen erhalten und wird bei einer
neuen Verarbeitung ersetzt.

Freigegebene Ersetzungen bilden eine untrennbare Worteinheit mit dem gesamten
ursprünglichen Zeitbereich. Es werden keine neuen Einzelwortzeiten erfunden.
Danach wird die gewählte Gruppierung neu durchgeführt. Original-Wortdaten
(`.words.original.json`) und Prüfentscheidungen (`.words.review.json`) werden
neben den freigegebenen Wortdaten gespeichert und zum Download angeboten.
Transkriptions-Checkpoints bleiben unverändert. Die Wortdaten sind auch bei
einem Prüfungsfehler weiterhin herunterladbar.

## Wiederholen ohne erneute Transkription

Neben der SRT wird eine `.words.json`-Datei mit den Originalworten und ihren
Zeitstempeln gespeichert. Über **Wortdaten erneut exportieren** kann diese Datei
mit anderen Einstellungen erneut verarbeitet werden, ohne Audio-API-Aufruf.
Zum Gegenhören kann unter **Audiodatei zum Gegenhören (lokaler Pfad, optional)**
die passende Datei auf dem Streamlit-Rechner angegeben werden. Bei einer
JSON mit dem Standardnamen `<Video-ID>.words.json` wird das zugehörige
YouTube-Audioarchiv vorbelegt, wenn die Datei vorhanden ist. Bei umbenannten
JSONs muss der Pfad selbst angegeben werden. Die JSON bleibt eine unveränderte
Wortliste; sie enthält keine Audiozuordnung. Es liegt in der Verantwortung des
Benutzers, eine zu den Wortzeiten passende Audiodatei auszuwählen.
Der Button **Wortdaten für erneuten Export herunterladen** stellt die Datei
auch auf einem Mobilgerät bereit, ohne Zugriff auf das Server-Dateisystem.
Er bleibt nach einem Fehler der LLM-Gruppierung und bei normalen
Oberflächen-Neuausführungen innerhalb derselben Sitzung verfügbar.
Eine SRT wird nur nach erfolgreichem Export zum Download angeboten.
Für einen Export ohne LLM ist dabei kein API-Schlüssel erforderlich.
Eine vorhandene SRT allein enthält keine verlässlichen Wort-Zeitstempel und
wird daher nicht als Eingabe unterstützt.

Transkriptions- und LLM-Zwischenstände bleiben unter `.transcription_cache`
erhalten und können in der Oberfläche ausdrücklich gelöscht werden.
LLM-Antworten werden nach Modell, Prompt, Einstellungen und Eingabewörtern
zwischengespeichert. Bei Fehlern bleibt der Fortschritt erhalten; eine eventuell
bereits geschriebene Zwischen-SRT ist noch kein erfolgreich korrigierter Export.
Beide JSON-Arten enthalten Transkriptinformationen und sollten entsprechend
vertraulich behandelt werden.

## Tests

`python -m unittest test_subtitles test_transcript_review test_media_sources test_youtube_video test_review_audio test_mobile_upload`
prüft Aufteilung, Worterhalt, Zeitgrenzen, LLM-Validierung, Anbieteradapter,
den Medienquellen-Vertrag und die Streamlit-Oberfläche mit gemockten API-Aufrufen.
Die Browser-Ereignistests des mobilen Ersatz-Uploads benötigen zusätzlich Node.js.