#!/usr/bin/env python3
"""Export SMS/iMessage chats for specific contacts from an iOS backup.

This utility reads the ``sms.db`` database that is produced by an unencrypted
Finder/iTunes backup (or a third-party extraction tool) and converts the chat
history for the requested contacts into human readable ``.txt`` transcripts.  If
requested, media attachments that still exist in the backup directory are copied
alongside the transcript.

Example usage::

    python export_ios_sms.py \
        --sms-db /path/to/backup/sms.db \
        --attachments-root /path/to/backup \
        --contact "+491701234567" --contact "Max Mustermann" \
        --output-dir ./exports --include-media

The script does **not** break any encryption.  If your backup is protected with
an iTunes password, you first need to create an unencrypted copy with tools such
as iMazing, iExplorer, or the native macOS Finder/iTunes export option.
"""
from __future__ import annotations

import argparse
import datetime as _dt
from pathlib import Path
import re
import shutil
import sqlite3
from typing import List, Optional, Sequence, Tuple


APPLE_EPOCH = _dt.datetime(2001, 1, 1)
ATTACHMENT_ANCHOR = re.compile(r"Library/SMS/Attachments/(.*)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export SMS/iMessage conversations for the given contacts "
        "from an iOS backup database."
    )
    parser.add_argument(
        "--sms-db",
        required=True,
        type=Path,
        help="Pfad zur sms.db Datei aus dem iOS-Backup.",
    )
    parser.add_argument(
        "--attachments-root",
        type=Path,
        default=None,
        help=(
            "Optionaler Pfad zum Root-Verzeichnis des Backups, das die "
            "'Library/SMS/Attachments'-Struktur enthält. Wird benötigt, um "
            "Mediendateien mit --include-media zu kopieren."
        ),
    )
    parser.add_argument(
        "--contact",
        dest="contacts",
        action="append",
        default=[],
        help=(
            "Kontaktbezeichner (Telefonnummer, E-Mail-Adresse oder Name), wie er "
            "im Nachrichten-Datenbankfeld 'handle.id' gespeichert ist. Dieses "
            "Argument kann mehrfach angegeben werden."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./ios_sms_exports"),
        help="Zielverzeichnis für Textdateien und optionale Medienanhänge.",
    )
    parser.add_argument(
        "--include-media",
        action="store_true",
        help="Anhänge (Fotos, Videos, Audio) in ein Unterverzeichnis kopieren.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Existierende Exportdateien überschreiben, statt den Export abzubrechen.",
    )

    args = parser.parse_args()
    if not args.contacts:
        parser.error("Mindestens ein --contact muss angegeben werden.")
    if args.include_media and not args.attachments_root:
        parser.error(
            "--attachments-root ist erforderlich, um Mediendateien zu exportieren."
        )
    return args


def apple_timestamp_to_datetime(value: Optional[int]) -> Optional[_dt.datetime]:
    """Convert Apple Core Data timestamps to :class:`datetime.datetime`.

    iOS speichert Zeitstempel seit dem 1. Januar 2001 in Nanosekunden. Ältere
    Backups können Sekundenwerte verwenden. Diese Hilfsfunktion normalisiert
    beide Varianten.
    """

    if value is None:
        return None
    try:
        # sqlite can return floats (Catalina) or ints (Big Sur+)
        value = int(value)
    except (TypeError, ValueError):
        return None

    if value == 0:
        return None

    # Werte größer als 10^12 sind üblicherweise Nanosekunden.
    if value > 10**12:
        seconds = value / 1_000_000_000
    else:
        seconds = value

    return APPLE_EPOCH + _dt.timedelta(seconds=seconds)


def sanitize_filename(handle: str) -> str:
    sanitized = re.sub(r"[^\w.-]+", "_", handle.strip())
    return sanitized or "contact"


def ensure_output_path(path: Path, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Die Datei '{path}' existiert bereits. Verwende --overwrite, um sie zu ersetzen."
        )
    path.parent.mkdir(parents=True, exist_ok=True)


def resolve_attachment_path(raw_path: Optional[str], attachments_root: Path) -> Optional[Path]:
    if not raw_path:
        return None
    match = ATTACHMENT_ANCHOR.search(raw_path)
    if not match:
        return None
    relative = Path(match.group(1))
    candidate = attachments_root / "Library" / "SMS" / "Attachments" / relative
    if candidate.exists():
        return candidate
    # Einige Exporte enthalten keine führende Struktur.
    candidate = attachments_root / relative
    return candidate if candidate.exists() else None


def fetch_messages(
    connection: sqlite3.Connection, handle_identifier: str
) -> List[sqlite3.Row]:
    query = """
        SELECT
            m.ROWID AS message_id,
            m.handle_id,
            m.date,
            m.is_from_me,
            m.text,
            m.cache_roomnames,
            a.filename,
            a.transfer_name,
            a.mime_type
        FROM message AS m
        JOIN handle AS h ON h.ROWID = m.handle_id
        LEFT JOIN message_attachment_join AS maj ON maj.message_id = m.ROWID
        LEFT JOIN attachment AS a ON a.ROWID = maj.attachment_id
        WHERE h.id = ?
        ORDER BY m.date, m.ROWID
    """
    cur = connection.execute(query, (handle_identifier,))
    return cur.fetchall()


def format_message(
    row: sqlite3.Row,
    handle_identifier: str,
    attachments_dir: Optional[Path],
    attachments_root: Optional[Path],
    include_media: bool,
) -> Tuple[str, List[str]]:
    timestamp = apple_timestamp_to_datetime(row["date"])
    if timestamp is None:
        timestamp_text = "Unbekannte Zeit"
    else:
        timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    sender = "Ich" if row["is_from_me"] else handle_identifier
    body = (row["text"] or "").replace("\r\n", "\n").replace("\r", "\n")
    if not body:
        body = "(kein Text)"

    attachments: List[str] = []
    attachment_path = None
    if include_media and attachments_dir and attachments_root:
        attachment_path = resolve_attachment_path(row["filename"], attachments_root)
        if attachment_path:
            attachments_dir.mkdir(parents=True, exist_ok=True)
            destination_name = row["transfer_name"] or attachment_path.name
            destination = attachments_dir / destination_name

            suffix = 1
            base_name = destination.stem
            suffix_str = destination.suffix
            while destination.exists():
                destination = attachments_dir / f"{base_name}_{suffix}{suffix_str}"
                suffix += 1

            shutil.copy2(attachment_path, destination)
            attachments.append(destination.name)

    if row["filename"] and include_media and not attachment_path:
        attachments.append("(Anhang nicht gefunden im Backup)")

    attachment_note = ""
    if attachments:
        attachment_note = " " + ", ".join(f"[Anhang: {name}]" for name in attachments)

    return f"[{timestamp_text}] {sender}: {body}{attachment_note}", attachments


def export_for_contact(
    connection: sqlite3.Connection,
    handle_identifier: str,
    output_dir: Path,
    attachments_root: Optional[Path],
    include_media: bool,
    overwrite: bool,
) -> Path:
    sanitized = sanitize_filename(handle_identifier)
    text_path = output_dir / f"{sanitized}.txt"
    ensure_output_path(text_path, overwrite=overwrite)

    attachments_dir: Optional[Path] = None
    if include_media:
        attachments_dir = output_dir / f"{sanitized}_attachments"
        if attachments_dir.exists() and not overwrite:
            raise FileExistsError(
                f"Das Verzeichnis '{attachments_dir}' existiert bereits. Verwende --overwrite."
            )
        if attachments_dir.exists() and overwrite:
            shutil.rmtree(attachments_dir)

    rows = fetch_messages(connection, handle_identifier)
    if not rows:
        raise ValueError(
            "Keine Nachrichten für Kontakt '{handle}' gefunden.".format(
                handle=handle_identifier
            )
        )

    with text_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            line, _ = format_message(
                row=row,
                handle_identifier=handle_identifier,
                attachments_dir=attachments_dir,
                attachments_root=attachments_root,
                include_media=include_media,
            )
            fh.write(line + "\n")

    return text_path


def export_chats(
    sms_db: Path,
    attachments_root: Optional[Path],
    contacts: Sequence[str],
    output_dir: Path,
    include_media: bool,
    overwrite: bool,
) -> List[Path]:
    connection = sqlite3.connect(str(sms_db))
    connection.row_factory = sqlite3.Row
    try:
        exported: List[Path] = []
        for handle_identifier in contacts:
            print(f"Exportiere Nachrichten für {handle_identifier!r}...")
            exported_path = export_for_contact(
                connection,
                handle_identifier=handle_identifier,
                output_dir=output_dir,
                attachments_root=attachments_root,
                include_media=include_media,
                overwrite=overwrite,
            )
            exported.append(exported_path)
    finally:
        connection.close()
    return exported


def main() -> None:
    args = parse_args()
    sms_db = args.sms_db.expanduser().resolve()
    if not sms_db.exists():
        raise FileNotFoundError(f"Die Datenbank '{sms_db}' wurde nicht gefunden.")

    attachments_root = None
    if args.attachments_root:
        attachments_root = args.attachments_root.expanduser().resolve()
        if not attachments_root.exists():
            raise FileNotFoundError(
                f"Das Anhangs-Verzeichnis '{attachments_root}' wurde nicht gefunden."
            )

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    exported_files = export_chats(
        sms_db=sms_db,
        attachments_root=attachments_root,
        contacts=args.contacts,
        output_dir=output_dir,
        include_media=args.include_media,
        overwrite=args.overwrite,
    )

    print("Fertig! Exportierte Dateien:")
    for file in exported_files:
        print(f" - {file}")


if __name__ == "__main__":
    main()
