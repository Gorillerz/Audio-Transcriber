"""Local speech-model IDs and display capabilities shared by UI and pipeline validation."""

DEFAULT_TRANSCRIPTION_MODEL_ID = "openai/whisper-medium"
TRANSCRIPTION_MODELS = {
    DEFAULT_TRANSCRIPTION_MODEL_ID: {
        "id": DEFAULT_TRANSCRIPTION_MODEL_ID,
        "name": "Whisper medium",
        "provider": "OpenAI Whisper running locally in WSL",
        "timing": "Word-level timestamps",
        "languages": "English and French; automatic language detection",
        "engine_model": "medium",
    },
}


def list_transcription_models() -> list[dict]:
    """Return UI-safe model metadata without exposing worker-specific launch names."""
    return [{key: value for key, value in model.items() if key != "engine_model"} for model in TRANSCRIPTION_MODELS.values()]
