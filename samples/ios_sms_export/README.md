# Export von iOS SMS-/iMessage-Chats

Dieses Beispielskript zeigt, wie sich Nachrichten für ausgewählte Kontakte aus
der `sms.db`-Datenbank eines iOS-Backups extrahieren lassen. Es generiert
Textprotokolle im Stil des WhatsApp-Exports und kann optional vorhandene
Mediendateien (Fotos, Videos, Audio) aus dem Backup kopieren.

## Voraussetzungen

1. Erstelle mit Finder/iTunes (macOS) oder dem iPhone-Backup-Tool deiner Wahl
   ein **nicht verschlüsseltes** Backup des Geräts.
2. Extrahiere daraus die Datei `sms.db`. Bei einem Finder- oder iTunes-Backup
   findest du die Datei nach dem Entschlüsseln zum Beispiel unter
   `~/Library/Application Support/MobileSync/Backup/<BACKUP-ID>/3d/3d0d7e5fb2ce288813306e4d4636395e047a3d28`.
   Viele Desktop-Tools können die Datei ebenfalls exportieren.
3. Wenn du Medien mitsichern möchtest, kopiere zusätzlich den Ordner
   `Library/SMS/Attachments` aus dem Backup. Übergebe dessen Wurzelpfad später
   als `--attachments-root`.
4. Stelle sicher, dass Python 3.8+ installiert ist.

## Nutzung

```bash
python export_ios_sms.py \
  --sms-db /pfad/zum/backup/sms.db \
  --attachments-root /pfad/zum/backup \
  --contact "+491701234567" \
  --contact "Max Mustermann" \
  --output-dir ./exports \
  --include-media
```

Wichtige Optionen:

- `--contact` kann mehrfach angegeben werden. Verwende Telefonnummern im selben
  Format, wie sie im iPhone angezeigt werden. Alternativ lassen sich E-Mail-
  Adressen (iMessage) oder Namen verwenden, sofern sie in `handle.id`
  gespeichert sind.
- `--include-media` sorgt dafür, dass Mediendateien in ein separates
  Unterverzeichnis kopiert werden. Ohne diese Option werden nur Textnachrichten
  exportiert.
- `--overwrite` überschreibt vorhandene Exporte. Standardmäßig bricht das
  Skript ab, wenn eine Zieldatei bereits existiert.

Nach erfolgreichem Durchlauf findest du für jeden Kontakt eine `*.txt`-Datei im
Ausgabeverzeichnis. Jeder Eintrag enthält einen Zeitstempel, den Absender ("Ich"
für gesendete Nachrichten) sowie einen Hinweis auf vorhandene Anhänge.
