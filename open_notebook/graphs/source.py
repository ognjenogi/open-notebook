import asyncio
import operator
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar
from urllib.parse import urlparse

import content_core as cc
from content_core import ContentCoreConfig, extract_content
from content_core.common import ExtractionOutput
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger
from typing_extensions import Annotated, TypedDict

from open_notebook.ai.models import Model, ModelManager
from open_notebook.ai.vision import describe_segment, vision_available
from open_notebook.config import UPLOADS_FOLDER
from open_notebook.domain.content_settings import ContentSettings
from open_notebook.domain.notebook import Asset, Source
from open_notebook.domain.transformation import Transformation
from open_notebook.domain.video_vision import merge_transcript_with_visual
from open_notebook.graphs.transformation import graph as transform_graph
from open_notebook.utils.runtime_capabilities import engine_runtime_missing
from open_notebook.utils.video_frames import extract_frames, ffprobe_duration

# content-core >= 2.1 disables its own Loguru logging for library consumers.
# Both the API and the worker import this module before extracting anything,
# so re-enable it here to keep extraction logs in their output.
logger.enable("content_core")

# Default preferred languages for YouTube transcript selection, used when
# ContentSettings.youtube_preferred_languages is unset. content-core's own
# default is only ["en", "es", "pt"]; we keep the broader list Open Notebook has
# always intended so non-English videos still resolve a transcript.
YOUTUBE_PREFERRED_LANGUAGES = [
    "en",
    "pt",
    "es",
    "de",
    "nl",
    "en-GB",
    "fr",
    "hi",
    "ja",
    "zh-CN",
    "zh-TW",
]


class SourceState(TypedDict):
    # Input describing what to extract: url / file_path / content / delete_source.
    content_state: Dict[str, Any]
    # Result of content-core extraction (does NOT echo url/file_path back).
    extraction: ExtractionOutput
    apply_transformations: List[Transformation]
    source_id: str
    notebook_ids: List[str]
    source: Source
    transformation: Annotated[list, operator.add]
    embed: bool


class TransformationState(TypedDict):
    source: Source
    transformation: Transformation


def _usable_engine(engine: str, kind: str) -> str:
    """Return ``engine``, or "auto" when its opt-in runtime is not installed.

    The engine choice is persisted in the database; runtime availability comes
    from environment flags that are re-evaluated on every boot. A redeploy that
    drops OPEN_NOTEBOOK_ENABLE_CRAWL4AI/_DOCLING (or a failed on-demand install)
    therefore leaves a stored selection pointing at an absent runtime, and
    passing it through fails every extraction with no usable diagnostic. Falling
    back to content-core's "auto" chain keeps ingestion working, loudly.
    """
    missing_env_var = engine_runtime_missing(engine)
    if missing_env_var is None:
        return engine
    logger.warning(
        f"Configured {kind} engine '{engine}' is selected in Content Settings but "
        f"its runtime is not available in this container; falling back to 'auto'. "
        f"Set {missing_env_var}=true to enable it (see ADR-007)."
    )
    return "auto"


T = TypeVar("T")


async def _run_blocking(fn: Callable[..., T], *args: Any) -> T:
    return await asyncio.to_thread(fn, *args)


async def get_stt_model():
    """Provisioned default speech-to-text model (with credentials), or None."""
    try:
        from open_notebook.ai.models import ModelManager

        return await ModelManager().get_speech_to_text()
    except Exception as e:
        logger.warning(f"STT model unavailable: {e}")
        return None


def download_youtube_audio(url: str) -> Optional[str]:
    """Download audio-only track of a YouTube video to a temp file.

    Tries yt-dlp (Android client, best bot resistance) then pytubefix.
    Returns the file path, or None when all downloaders fail. Callers unlink.
    """
    try:
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="onb-yt-")
        out = f"{tmpdir}/audio.%(ext)s"
        try:
            from yt_dlp import YoutubeDL

            for client in ("android", "web"):
                try:
                    with YoutubeDL(
                        {
                            "format": "bestaudio/best",
                            "outtmpl": out,
                            "quiet": True,
                            "no_warnings": True,
                            "extractor_args": {"youtube": {"player_client": [client]}},
                        }
                    ) as ydl:
                        ydl.download([url])
                    import glob as _glob

                    files = _glob.glob(f"{tmpdir}/audio.*")
                    if files:
                        return files[0]
                except Exception as e:
                    logger.warning(
                        f"YouTube audio download via yt-dlp/{client} failed: {e}"
                    )
        except ImportError:
            pass
        try:
            from pytubefix import YouTube

            yt = YouTube(url)
            stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
            if stream is not None:
                return stream.download(output_path=tmpdir, filename="audio.mp4")
        except Exception as e:
            logger.warning(f"YouTube audio download via pytubefix failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"YouTube audio download failed for {url}: {e}")
        return None


async def transcribe_youtube_audio(url: str) -> Optional[str]:
    """Best-effort YouTube audio transcription. Returns text or None."""
    stt = await get_stt_model()
    if stt is None:
        return None
    path = await _run_blocking(download_youtube_audio, url)
    if not path:
        return None
    try:
        result = await stt.atranscribe(path)
        text = (getattr(result, "text", "") or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"YouTube audio transcription failed for {url}: {e}")
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def download_youtube_video(url: str) -> Optional[str]:
    """Download a YouTube video (<=720p mp4) to a temp file.

    Tries yt-dlp (Android client, best bot resistance) then pytubefix.
    Returns the file path, or None when all downloaders fail. Callers unlink.
    """
    try:
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="onb-ytv-")
        out = f"{tmpdir}/video.%(ext)s"
        try:
            from yt_dlp import YoutubeDL

            for client in ("android", "web"):
                try:
                    with YoutubeDL(
                        {
                            "format": "best[height<=720][ext=mp4]/best[height<=720]/best",
                            "outtmpl": out,
                            "quiet": True,
                            "no_warnings": True,
                            "extractor_args": {"youtube": {"player_client": [client]}},
                        }
                    ) as ydl:
                        ydl.download([url])
                    import glob as _glob

                    files = _glob.glob(f"{tmpdir}/video.*")
                    if files:
                        return files[0]
                except Exception as e:
                    logger.warning(
                        f"YouTube video download via yt-dlp/{client} failed: {e}"
                    )
        except ImportError:
            pass
        try:
            from pytubefix import YouTube

            yt = YouTube(url)
            stream = (
                yt.streams.filter(progressive=True, file_extension="mp4")
                .order_by("resolution")
                .desc()
                .first()
            )
            if stream is not None:
                return stream.download(output_path=tmpdir, filename="video.mp4")
        except Exception as e:
            logger.warning(f"YouTube video download via pytubefix failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"YouTube video download failed for {url}: {e}")
        return None


_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".m4v",
    ".ogv",
    ".mpg",
    ".mpeg",
}

_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".wma",
    ".opus",
}


def _looks_like_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _AUDIO_EXTENSIONS


def extract_audio_from_media(file_path: str) -> Optional[str]:
    """Extract an audio track from a media file to a temp mp3 using ffmpeg.

    Returns the path to the temp mp3 file or None if extraction fails / no audio stream.
    Caller unlinks the temp file and its parent temp dir.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _AUDIO_EXTENSIONS:
        return None  # Already audio, transcribe directly
    tmpdir = tempfile.mkdtemp(prefix="onb-audio-")
    out = os.path.join(tmpdir, "audio.mp3")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                file_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                out,
            ],
            capture_output=True,
            check=True,
        )
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    except Exception as e:
        logger.debug(f"Audio extraction from {file_path} failed or no audio stream: {e}")
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass
    return None


async def transcribe_media_file(file_path: str) -> Optional[str]:
    """Transcribe an uploaded audio or video file via the configured STT model. Returns text or None."""
    stt = await get_stt_model()
    if stt is None:
        logger.warning(f"No STT model available for media transcription of {file_path}")
        return None
    extracted_audio = await _run_blocking(extract_audio_from_media, file_path)
    target_path = extracted_audio if extracted_audio else file_path
    try:
        result = await stt.atranscribe(target_path)
        text = (getattr(result, "text", "") or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"Media transcription failed for {file_path}: {e}")
        return None
    finally:
        if extracted_audio:
            try:
                os.unlink(extracted_audio)
                shutil.rmtree(os.path.dirname(extracted_audio), ignore_errors=True)
            except OSError:
                pass


VISION_SEGMENT_SIZE = 6

# Maximum persisted frames per video (up to 8 key frames across segments).
MAX_PERSISTED_FRAMES = 8

# Public URL root for persisted frames (served by the StaticFiles mount in
# api/main.py). The engine rewrites these to its /api/notebook-asset proxy.
FRAME_URL_ROOT = "/assets/uploads"


def _persist_segment_frame(jpeg_path: str, start: float) -> Optional[str]:
    """Copy a segment's first frame into UPLOADS_FOLDER; return its public
    URL, or None when anything goes wrong (frames are best-effort)."""
    try:
        name = f"{uuid.uuid4().hex[:12]}-frame{int(start)}s.jpg"
        dest = os.path.join(UPLOADS_FOLDER, name)
        os.makedirs(UPLOADS_FOLDER, exist_ok=True)
        shutil.copy(jpeg_path, dest)
        return f"{FRAME_URL_ROOT}/{name}"
    except Exception as e:
        logger.warning(f"Frame persistence failed for {jpeg_path}: {e}")
        return None


def _looks_like_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _VIDEO_EXTENSIONS


async def _resolve_upload_video(file_path: str) -> Optional[str]:
    """Return ``file_path`` when it is a video, else None. Never raises.

    Extension allowlist is the fast path; anything else is probed with
    ffprobe (an audio-only or non-media file probes fine or fails closed —
    vision_enhance still degrades to transcript-only downstream).
    """
    if _looks_like_video(file_path):
        return file_path
    try:
        await _run_blocking(ffprobe_duration, file_path)
        return file_path
    except Exception:
        return None


def _cleanup_frames(frames: List[Tuple[float, str]]) -> None:
    seen_dirs = set()
    for _, jpeg_path in frames:
        try:
            os.unlink(jpeg_path)
        except OSError:
            pass
        seen_dirs.add(os.path.dirname(jpeg_path))
    for tmpdir in seen_dirs:
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


async def vision_enhance(video_path: str, transcript: str) -> Optional[str]:
    """Describe video frames per segment and return markdown notes, or None.

    Frames are grouped into segments of 6; each segment gets a transcript
    excerpt sliced by proportional character offset and a duration hint.
    Never raises: any failure is logged and yields None (transcript-only).
    """
    try:
        frames = await _run_blocking(extract_frames, video_path)
        if not frames:
            return None
        try:
            duration = await _run_blocking(ffprobe_duration, video_path)
        except Exception:
            duration = frames[-1][0] + 10.0
        if duration <= 0:
            duration = frames[-1][0] + 10.0 or 10.0
        try:
            segments = [
                frames[i : i + VISION_SEGMENT_SIZE]
                for i in range(0, len(frames), VISION_SEGMENT_SIZE)
            ]
            total = len(transcript)
            parts: List[str] = []
            persisted = 0
            for index, segment in enumerate(segments):
                seg_start = segment[0][0]
                if index + 1 < len(segments):
                    seg_end = segments[index + 1][0][0]
                else:
                    seg_end = duration
                excerpt = transcript[
                    round(total * seg_start / duration) : round(
                        total * seg_end / duration
                    )
                ]
                duration_hint = f"{seg_start:.0f}s-{seg_end:.0f}s of {duration:.0f}s"
                description = await describe_segment(
                    list(segment), excerpt, duration_hint
                )
                persisted_frames: List[Tuple[float, str]] = []
                # Candidate frame indices within this segment:
                # Always start with frame 0. If segment has >= 4 frames (typical 6-frame segment),
                # also sample an intermediate frame (middle or later) so slide-heavy lectures
                # do not lose intermediate slides.
                candidates = [0]
                if len(segment) >= 4:
                    candidates.append(len(segment) // 2)

                for c_idx in candidates:
                    if persisted >= MAX_PERSISTED_FRAMES:
                        break
                    f_time, f_path = segment[c_idx]
                    f_url = _persist_segment_frame(f_path, f_time)
                    if f_url is not None:
                        persisted_frames.append((f_time, f_url))
                        persisted += 1

                if persisted_frames:
                    img_md = "\n\n".join(
                        f"![frame @ {t:.0f}s]({url})" for t, url in persisted_frames
                    )
                    parts.append(
                        f"### {seg_start:.0f}s\n\n{img_md}\n\n{description}"
                    )
                else:
                    parts.append(f"### {seg_start:.0f}s\n\n{description}")
            return "\n\n".join(parts) or None
        finally:
            _cleanup_frames(frames)
    except Exception as e:
        logger.warning(f"Vision pass failed for {video_path}: {e}")
        return None


def _is_youtube_url(url: str) -> bool:
    """Whether ``url`` points at YouTube (by hostname, not substring)."""
    host = (urlparse(url).hostname or "").lower()
    return host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com")


_YOUTUBE_NO_TRANSCRIPT_MESSAGE = (
    "Could not extract content from this YouTube video. "
    "No transcript or subtitles are available. "
    "Try configuring a Speech-to-Text model in Settings "
    "to transcribe the audio instead."
)


def _extraction_error(error: "cc.ContentCoreError", url: str) -> ValueError:
    """Turn a content-core extraction error into a user-facing permanent failure.

    content-core >= 2.2 raises typed errors instead of returning empty content.
    They are all treated as permanent (ValueError is in process_source's
    stop_on): content-core already retries transient failures internally,
    including NetworkError, and our worker's 15 attempts exist for SurrealDB
    transaction conflicts, not for re-fetching an unreachable page. A failed
    source can still be retried from the UI.

    The message is fixed per type: content-core's own text can carry proxy
    credentials, local paths or configuration details, so it only goes to the
    worker log (logged by the caller, and kept as the exception's cause).
    """

    if isinstance(error, cc.NoTranscriptFound):
        return ValueError(_YOUTUBE_NO_TRANSCRIPT_MESSAGE)
    # content-core reports a failure of both YouTube transcript paths (e.g.
    # IpBlocked) as "YouTube transcript extraction failed ..."; other
    # ExternalServiceErrors on a YouTube URL (speech-to-text provider, fetch
    # engine) get the generic message below.
    if (
        isinstance(error, cc.ExternalServiceError)
        and url
        and _is_youtube_url(url)
        and "youtube transcript" in str(error).lower()
    ):
        return ValueError(
            "YouTube blocked or failed the transcript request. If this keeps "
            "happening, set CCORE_YOUTUBE_PROXY (a residential proxy) or "
            "CCORE_YOUTUBE_COOKIES_FILE for the worker."
        )
    if isinstance(error, cc.NotFoundError):
        return ValueError(
            "The page was not found (it may have been removed or moved). Check the URL."
        )
    if isinstance(error, cc.NetworkError):
        return ValueError(
            "Could not reach this address (connection, timeout or DNS error). "
            "Check the URL and try again."
        )
    if isinstance(error, cc.InvalidInputError):
        return ValueError("This URL or input is not valid.")
    if isinstance(error, cc.UnsupportedTypeException):
        return ValueError("This file type is not supported.")
    if isinstance(error, cc.FileOperationError):
        return ValueError(
            "The file could not be read. It may be corrupted or in an "
            "unsupported format."
        )
    if isinstance(error, cc.ConfigurationError):
        return ValueError(
            "Content extraction is not configured correctly. Check the content "
            "processing engine and speech-to-text settings; the worker log has "
            "the details."
        )
    if isinstance(error, cc.ExternalServiceError):
        return ValueError("The content extraction service failed.")
    return ValueError("Could not extract content from this source.")


async def content_process(state: SourceState) -> dict:
    content_state: Dict[str, Any] = state["content_state"]

    # content-core 2.x takes engine/model overrides via ContentCoreConfig
    # (keyword-only), not inside the input dict.
    config_kwargs: Dict[str, Any] = {
        "youtube_languages": YOUTUBE_PREFERRED_LANGUAGES,
    }

    # Honor the persisted content-processing engine choices. content-core
    # accepts "auto"/"simple"/"firecrawl"/"jina"/"crawl4ai" for URLs and
    # "auto"/"docling"/"simple" for documents; falling back to "auto" keeps the
    # previous behavior when settings are unset.
    video_vision = True
    try:
        settings: ContentSettings = await ContentSettings.get_instance()  # type: ignore[assignment]
        if settings.youtube_preferred_languages:
            config_kwargs["youtube_languages"] = settings.youtube_preferred_languages
        if settings.default_content_processing_engine_url:
            config_kwargs["url_engine"] = _usable_engine(
                settings.default_content_processing_engine_url, "url"
            )
        if settings.default_content_processing_engine_doc:
            config_kwargs["document_engine"] = _usable_engine(
                settings.default_content_processing_engine_doc, "document"
            )
        if settings.docling_ocr is not None:
            config_kwargs["docling_ocr"] = settings.docling_ocr
        if settings.docling_formulas is not None:
            config_kwargs["docling_formulas"] = settings.docling_formulas
        if settings.docling_vision is not None:
            config_kwargs["docling_vision"] = settings.docling_vision
        if settings.video_vision is not None:
            video_vision = settings.video_vision
    except Exception as e:
        # Keep the server-side traceback for diagnosing DB/deserialization
        # failures while still falling back to defaults (non-fatal).
        logger.opt(exception=True).warning(
            f"Failed to load content settings, using defaults: {e}"
        )

    try:
        model_manager = ModelManager()
        defaults = await model_manager.get_defaults()
        if defaults.default_speech_to_text_model:
            stt_model = await Model.get(defaults.default_speech_to_text_model)
            if stt_model:
                config_kwargs["audio_provider"] = stt_model.provider
                config_kwargs["audio_model"] = stt_model.name
                logger.debug(
                    f"Using speech-to-text model: {stt_model.provider}/{stt_model.name}"
                )
    except Exception as e:
        logger.warning(f"Failed to retrieve speech-to-text model configuration: {e}")
        # Continue without custom audio model (content-core will use its default)

    config = ContentCoreConfig(**config_kwargs) if config_kwargs else None

    # Log the effective extraction engines so operators can confirm which engine
    # actually ran (content-core logs its own dispatch only at DEBUG). Absent
    # overrides fall back to content-core's "auto".
    if content_state.get("url"):
        target = "url"
    elif content_state.get("file_path"):
        target = "document"
    else:
        target = "content"
    logger.info(
        f"Extracting {target} via content-core "
        f"(url_engine={config_kwargs.get('url_engine', 'auto')}, "
        f"document_engine={config_kwargs.get('document_engine', 'auto')}, "
        f"docling_ocr={config_kwargs.get('docling_ocr', 'auto')}, "
        f"docling_formulas={config_kwargs.get('docling_formulas', 'auto')}, "
        f"docling_vision={config_kwargs.get('docling_vision', 'auto')})"
    )

    url = content_state.get("url") or ""
    try:
        processed = await extract_content(
            url=content_state.get("url"),
            file_path=content_state.get("file_path"),
            content=content_state.get("content"),
            config=config,
        )
    except cc.ContentCoreError as e:
        file_path = content_state.get("file_path") or ""
        url = content_state.get("url") or ""
        if (file_path and (_looks_like_video(file_path) or _looks_like_audio(file_path))) or (url and _is_youtube_url(url)):
            logger.info(f"content-core extraction raised {type(e).__name__} for media source; trying STT/vision fallback")
            processed = ExtractionOutput(
                title=os.path.basename(file_path) if file_path else url,
                content="",
                metadata={},
            )
        else:
            logger.warning(f"content-core extraction failed ({type(e).__name__}): {e}")
            raise _extraction_error(e, url) from e
    except Exception as e:
        logger.warning(f"content-core extraction raised: {e}")
        file_path = content_state.get("file_path") or ""
        url = content_state.get("url") or ""
        if (file_path and (_looks_like_video(file_path) or _looks_like_audio(file_path))) or (url and _is_youtube_url(url)):
            processed = ExtractionOutput(
                title=os.path.basename(file_path) if file_path else url,
                content="",
                metadata={},
            )
        else:
            raise

    # content-core signals a soft extraction failure (e.g. an unreachable or
    # invalid URL, via the bs4 fallback) by returning title="Error" and content
    # prefixed with "Failed to extract content:" instead of raising. Detect that
    # sentinel and raise so the job is marked failed and the source becomes
    # retryable, rather than being saved as a "completed" source whose body is
    # the error string.
    if processed.title == "Error" and (processed.content or "").startswith(
        "Failed to extract content:"
    ):
        raise ValueError(
            "Could not extract content from this source. "
            "The URL or file may be unreachable, invalid, or in an unsupported format."
        )

    # Since content-core 2.2, empty content means the source was genuinely
    # empty; extraction failures raise (handled above).
    if not processed.content or not processed.content.strip():
        url = content_state.get("url") or ""
        file_path = content_state.get("file_path") or ""
        if url and ("youtube.com" in url or "youtu.be" in url):
            # Captions missing — fall back to audio download + STT instead
            # of failing. The configured default STT carries credentials.
            transcript = await transcribe_youtube_audio(url)
            if transcript:
                processed = ExtractionOutput(
                    title=processed.title or url,
                    content=transcript,
                    metadata=dict(processed.metadata or {}),
                )
            elif video_vision and vision_available():
                # Allow video vision fallback if STT failed/unavailable
                processed = ExtractionOutput(
                    title=processed.title or url,
                    content="",
                    metadata=dict(processed.metadata or {}),
                )
            else:
                raise ValueError(
                    "Could not extract content from this YouTube video. "
                    "No transcript or subtitles are available and audio "
                    "transcription failed. Try configuring a Speech-to-Text "
                    "model in Settings to transcribe the audio instead."
                )
        elif file_path and (_looks_like_video(file_path) or _looks_like_audio(file_path)):
            transcript = await transcribe_media_file(file_path)
            if transcript:
                processed = ExtractionOutput(
                    title=processed.title or os.path.basename(file_path),
                    content=transcript,
                    metadata=dict(processed.metadata or {}),
                )
            elif _looks_like_video(file_path) and video_vision and vision_available():
                # Vision-only video ingestion: audio is absent or empty, but
                # video frames will provide visual teaching notes.
                processed = ExtractionOutput(
                    title=processed.title or os.path.basename(file_path),
                    content="",
                    metadata=dict(processed.metadata or {}),
                )
            else:
                raise ValueError(
                    f"Could not extract any content from media file {os.path.basename(file_path)}. "
                    "Audio transcription returned no text and video vision is unavailable."
                )
        else:
            raise ValueError(
                "Could not extract any text content from this source. "
                "The content may be empty, inaccessible, or in an unsupported format."
            )

    # Vision pass: watch video frames with a dedicated vision model and merge
    # the visual notes into the transcript. Never raises — any failure,
    # including a raising gate, keeps the transcript-only source.
    video_path: Optional[str] = None
    temp_video = False
    try:
        if video_vision and vision_available():
            file_path = content_state.get("file_path")
            if file_path:
                video_path = await _resolve_upload_video(file_path)
            else:
                url = content_state.get("url") or ""
                if url and ("youtube.com" in url or "youtu.be" in url):
                    video_path = await _run_blocking(download_youtube_video, url)
                    temp_video = video_path is not None
            if video_path:
                visual = await vision_enhance(video_path, processed.content or "")
                if visual:
                    merged = (
                        merge_transcript_with_visual(processed.content, visual)
                        if processed.content and processed.content.strip()
                        else f"## Visual detail (from video frames)\n\n{visual}"
                    )
                    processed = ExtractionOutput(
                        title=processed.title,
                        content=merged,
                        metadata=dict(processed.metadata or {}),
                    )
    except Exception:
        logger.warning("vision pass failed; source kept transcript-only", exc_info=True)
    finally:
        if temp_video and video_path:
            try:
                os.unlink(video_path)
            except OSError:
                pass
            shutil.rmtree(os.path.dirname(video_path), ignore_errors=True)

    if not processed.content or not processed.content.strip():
        if url and _is_youtube_url(url):
            raise ValueError(_YOUTUBE_NO_TRANSCRIPT_MESSAGE)
        raise ValueError(
            "Could not extract any text or visual content from this source. "
            "The content may be empty, inaccessible, or in an unsupported format."
        )

    # content-core 2.x no longer deletes the uploaded source file after
    # extraction (the delete_source flag it used to honor is gone). Preserve the
    # previous auto-delete behavior on our side.
    if content_state.get("delete_source") and content_state.get("file_path"):
        file_path = content_state["file_path"]
        try:
            os.unlink(file_path)
        except FileNotFoundError:
            logger.warning(f"File not found while trying to delete: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to delete source file {file_path}: {e}")

    return {"extraction": processed}


async def save_source(state: SourceState) -> dict:
    content_state = state["content_state"]
    extraction = state["extraction"]

    # Get existing source using the provided source_id
    source = await Source.get(state["source_id"])
    if not source:
        raise ValueError(f"Source with ID {state['source_id']} not found")

    # Update the source with processed content. content-core's ExtractionOutput
    # does not echo url/file_path back, so carry them from the input state.
    source.asset = Asset(
        url=content_state.get("url"), file_path=content_state.get("file_path")
    )
    source.full_text = extraction.content

    # Preserve user-set title; only overwrite placeholder or empty titles
    if extraction.title and (not source.title or source.title == "Processing..."):
        source.title = extraction.title

    await source.save()

    # NOTE: Notebook associations are created by the API immediately for UI responsiveness
    # No need to create them here to avoid duplicate edges

    if state["embed"]:
        if source.full_text and source.full_text.strip():
            logger.debug("Embedding content for vector search")
            await source.vectorize()
        else:
            logger.warning(
                f"Source {source.id} has no text content to embed, skipping vectorization"
            )

    return {"source": source}


def trigger_transformations(state: SourceState, config: RunnableConfig) -> List[Send]:
    if len(state["apply_transformations"]) == 0:
        return []

    to_apply = state["apply_transformations"]
    logger.debug(f"Applying transformations {to_apply}")

    return [
        Send(
            "transform_content",
            {
                "source": state["source"],
                "transformation": t,
            },
        )
        for t in to_apply
    ]


async def transform_content(state: TransformationState) -> Optional[dict]:
    source = state["source"]
    content = source.full_text
    # Whitespace-only text would hit the transformation graph's empty-content
    # guard; skip it here like empty text.
    if not content or not content.strip():
        return None
    transformation: Transformation = state["transformation"]

    logger.debug(f"Applying transformation {transformation.name}")
    # LangGraph accepts a partial state dict at runtime, but its typed
    # overloads require the full state type (langgraph typing limitation).
    result = await transform_graph.ainvoke(  # type: ignore[call-overload]
        dict(input_text=content, transformation=transformation),
        config=RunnableConfig(configurable={"model_id": transformation.model_id}),
    )
    await source.add_insight(transformation.title, result["output"])
    return {
        "transformation": [
            {
                "output": result["output"],
                "transformation_name": transformation.name,
            }
        ]
    }


# Create and compile the workflow
workflow = StateGraph(SourceState)

# Add nodes
workflow.add_node("content_process", content_process)
workflow.add_node("save_source", save_source)
workflow.add_node("transform_content", transform_content)
# Define the graph edges
workflow.add_edge(START, "content_process")
workflow.add_edge("content_process", "save_source")
workflow.add_conditional_edges(
    "save_source", trigger_transformations, ["transform_content"]
)
workflow.add_edge("transform_content", END)

# Compile the graph
source_graph = workflow.compile()
