"""Merge helper for vision-based video ingestion."""


def merge_transcript_with_visual(transcript: str, visual: str) -> str:
    """Append vision-model notes under a fixed heading (deterministic append)."""
    return transcript + "\n\n## Visual detail (from video frames)\n\n" + visual
