"""MVP1 tests for file import, identity, metadata fallbacks, and catalog persistence."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

import app.storage as storage
from app.storage import Catalog


def test_import_records_hash_and_survives_catalog_reopen(tmp_path):
    """Imported bytes receive a stable row that can be read after reopening SQLite."""
    library = tmp_path / "library"
    first = Catalog(library)
    audio_bytes = b"not real audio; duration is expected to be unavailable"
    recording, duplicate, candidates = first.import_file("morning.wav", BytesIO(audio_bytes), "audio/wav")

    assert duplicate is False
    assert candidates == []
    assert recording["original_name"] == "morning.wav"
    assert recording["duration_seconds"] is None
    assert recording["status"] == "untranscribed"
    assert Catalog(library).get_recording(recording["id"])["sha256"] == recording["sha256"]


def test_exact_bytes_under_new_name_are_recognized_as_same_recording(tmp_path):
    """A rename does not create a second catalog row when content hash matches."""
    catalog = Catalog(tmp_path / "library")
    payload = b"identical audio bytes"
    original, _, _ = catalog.import_file("old-name.mp3", BytesIO(payload), "audio/mpeg")
    duplicate, is_duplicate, _ = catalog.import_file("new-name.mp3", BytesIO(payload), "audio/mpeg")

    assert is_duplicate is True
    assert duplicate["id"] == original["id"]
    assert len(catalog.list_recordings()) == 1
    assert catalog.get_recording(original["id"])["aliases"][0]["original_name"] == "new-name.mp3"


def test_unsupported_file_is_rejected_without_catalog_row(tmp_path):
    """Unsupported extensions return a useful error without creating a row."""
    catalog = Catalog(tmp_path / "library")

    with pytest.raises(ValueError, match="Unsupported audio format"):
        catalog.import_file("notes.txt", BytesIO(b"hello"), "text/plain")

    assert catalog.list_recordings() == []


def test_wave_duration_is_read_from_standard_library(tmp_path):
    """A supported WAV file exposes its duration even when it has no embedded tags."""
    wav = BytesIO()
    with wave.open(wav, "wb") as output:
        output.setparams((1, 2, 8000, 8000, "NONE", "not compressed"))
        output.writeframes(b"\x00\x00" * 8000)
    wav.seek(0)

    recording, _, _ = Catalog(tmp_path / "library").import_file("one-second.wav", wav, "audio/wav")

    assert recording["duration_seconds"] == 1.0


def test_mp3_duration_uses_format_parser_when_generic_detection_has_no_info(tmp_path, monkeypatch):
    """MP3 ID3-only detection falls back to Mutagen's MP3 parser for audio length."""
    monkeypatch.setattr(storage, "MutagenFile", lambda _path: {})
    monkeypatch.setattr(storage, "MP3", lambda _path: SimpleNamespace(info=SimpleNamespace(length=12.5)))

    duration, _ = Catalog._media_metadata(tmp_path / "recording.mp3")

    assert duration == 12.5


def test_metadata_match_requires_explicit_user_confirmation(tmp_path):
    """Same-size, same-duration files are candidates until the user confirms."""
    def wave_bytes(sample: bytes) -> bytes:
        payload = BytesIO()
        with wave.open(payload, "wb") as output:
            output.setparams((1, 2, 8000, 8000, "NONE", "not compressed"))
            output.writeframes(sample * 8000)
        return payload.getvalue()

    catalog = Catalog(tmp_path / "library")
    original, _, _ = catalog.import_file("original.wav", BytesIO(wave_bytes(b"\x00\x00")), "audio/wav")
    candidate, duplicate, matches = catalog.import_file("possible-copy.wav", BytesIO(wave_bytes(b"\x01\x00")), "audio/wav")

    assert duplicate is False
    assert candidate["possible_match_id"] == original["id"]
    assert matches[0]["id"] == original["id"]
    linked = catalog.confirm_match(candidate["id"], original["id"])
    assert linked is not None
    assert len(catalog.list_recordings()) == 1
    assert linked["aliases"][0]["original_name"] == "possible-copy.wav"


def test_existing_transcription_status_can_be_marked_and_corrected(tmp_path):
    """Manual legacy status is persisted and can be corrected from the details view."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("legacy.wav", BytesIO(b"audio"), "audio/wav")

    marked = catalog.set_status(recording["id"], "transcribed")
    assert marked["status"] == "transcribed"
    assert marked["status_source"] == "manual"
    corrected = catalog.set_status(recording["id"], "untranscribed")
    assert corrected["status"] == "untranscribed"
    assert corrected["status_source"] == "manual"


def test_delete_moves_audio_to_trash_before_removing_catalog_entry(tmp_path, monkeypatch):
    """A confirmed delete delegates to system trash and removes the catalog row."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("remove.wav", BytesIO(b"audio"), "audio/wav")
    sent_to_trash = []

    def fake_send2trash(path):
        sent_to_trash.append(path)
        Path(path).unlink()

    monkeypatch.setattr(storage, "send2trash", fake_send2trash)
    assert catalog.move_to_trash(recording["id"]) is True
    assert sent_to_trash == [recording["stored_path"]]
    assert catalog.get_recording(recording["id"]) is None
    assert not Path(recording["stored_path"]).exists()
