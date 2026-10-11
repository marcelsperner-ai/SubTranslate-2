# SubTranslate-2

## Lokale Transcripe-Anbindung

Unter **Standard-Einstellungen > Transcripe** den Ausgabe-Stammordner von
Transcripe konfigurieren und den automatischen Import aktivieren. Die Pfade
muessen auf dem Rechner erreichbar sein, auf dem das Flask-Backend laeuft.
Windows-Beispiel: `C:\Users\marce\Documents\Subtitles`.

Zum Starten ueber **Transkribieren** zusaetzlich den Transcripe-App-Ordner und
dessen eigenen Python-Interpreter angeben, beispielsweise
`C:\Users\marce\Documents\Transcripe\Transcribe` und die darin enthaltene
`.venv\Scripts\python.exe`. Eine bereits auf `127.0.0.1:8501` erreichbare
Streamlit-App wird wiederverwendet. Startfehler stehen auch in
`instance/transcripe-server.log`. Der gestartete Server wird von SubTranslate
nicht automatisch beendet; insbesondere muss Transcripe bis zum Videoabschluss
weiterlaufen.

### Importverhalten

- Der aktivierte Importdienst prueft alle fuenf Sekunden und nach einem
  SubTranslate-Neustart auch bereits vorhandene Marker. **Jetzt pruefen**
  speichert die Transcripe-Einstellungen und loest einen Scan aus.
- Nur `*.ready.json` nach Transcripe-Vertrag Version 1 bestaetigt ein fertiges
  Transkript. SRT und Wortdaten allein loesen keinen Import aus.
- Alle sechs Dateifelder `srt`, `words`, `metadata`, `words_original`,
  `words_review`, `audio` sind erforderlich. SRT und Wortdaten sind nicht-null;
  die anderen duerfen null sein. `sha256` enthaelt genau die nicht-null Felder
  mit 64-stelligen, kleingeschriebenen SHA-256-Pruefsummen.
- Relative Windows- und POSIX-Pfade werden unterhalb des Auftragsordners
  aufgeloest. Absolute Pfade, Pfadausbrueche und externe Symlinkziele werden
  abgelehnt. `.media` und `.transcription_cache` sind keine Markerquellen.
- SRT, JSON und Audio werden in eine eigene Ablage kopiert; die Pruefsummen
  der Kopien werden vor Bestaetigung kontrolliert. Jede neue UUID erzeugt
  genau ein neues **pausiertes** Projekt. Bestehende Projekte werden nicht
  ueberschrieben. Die Export-ID wird dauerhaft in SQLite gespeichert.
- Die deutsche SRT fuer die vorhandenen Uebersetzungsdienste erhaelt einen
  kollisionsfreien Namen mit Export-ID. Originaldateiname und Quelldateien
  bleiben ueber die Importzuordnung erhalten. Die Zusatzdateien liegen unter
  `uploads/transcripe/<export_id>/`.
- Titel, Kanal und Beschreibung aus der optionalen YouTube-JSON erzeugen
  den Kontext im bestehenden Zusammenfassungsfeld. Er wird in den Prompt
  uebernommen und kann dort projektspezifisch bearbeitet werden. Fehlende
  Metadaten blockieren den Import nicht.
- `*.media.json` mit gleicher Export-ID ordnet ein Video separat zu.
  Vor dem Projektimport erkannte Meldungen bleiben ausstehend und werden
  erneut geprueft. Auch das Video wird kopiert und anhand seiner Pruefsumme
  bestaetigt. Neue Export-IDs werden niemals einem alten Projekt zugeordnet.
- Status und Fehler stehen in der Seitenleiste und im Transcripe-Settings-Tab.
  Fehlerhafte Pakete werden beim naechsten Scan erneut versucht. Bei einer
  durch Prozessabbruch verbliebenen Ablage ohne Datenbankzuordnung wird ein
  sichtbarer Fehler gemeldet statt Dateien still zu ueberschreiben.

Genuegend freien Speicher fuer Audio-/Videokopien vorsehen. Gleichzeitige
Schreibvorgaenge in Transcripe auf dieselbe Dateibasis sind weiterhin nicht
unterstuetzt. Die Integration ist fuer vertrauenswuerdige lokale Nutzung
gedacht. Gemini-Glossarerstellung gehoert noch nicht zu dieser ersten Stufe;
beim Import wird nichts an Gemini gesendet.

### Video mit Untertiteln abspielen

In **EdTech > Main** startet **Video mit Untertiteln in VLC abspielen** den
lokalen VLC-Player mit dem gespeicherten Transcripe-Video. Der Button wird
nach Erzeugung der persischen SRT und Zuordnung des Videos freigeschaltet.
Verwendet wird die erzeugte ASS, sobald EdTech abgeschlossen ist und die
Datei vorhanden ist; andernfalls die persische SRT. ASS stellt auch die
EdTech-Infoboxen und Formatierungen dar. Eine neue Wiedergabe nach einer
Neugenerierung verwendet die aktuellen Untertitel.

VLC muss auf dem Rechner des Flask-Backends installiert sein. Die Anwendung
sucht im PATH und in den Windows-Standardordnern von VideoLAN. Bei einer
anderen Installation vor dem Start `SUBTRANSLATE_VLC_PATH` auf den kompletten
Pfad zu `vlc.exe` setzen. Startfehler werden direkt beim Button angezeigt.
Der Start ist nur von einem lokalen Browser erlaubt. VLC wird als eigene
Instanz gestartet und beim Beenden von SubTranslate nicht geschlossen.