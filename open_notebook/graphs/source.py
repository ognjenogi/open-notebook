import asyncio
import operator
import os
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from content_core import ContentCoreConfig, extract_content
from content_core.common import ExtractionOutput
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger
from typing_extensions import Annotated, TypedDict

from open_notebook.ai.models import Model, ModelManager
from open_notebook.ai.vision import describe_segment, vision_available
from open_notebook.domain.content_settings import ContentSettings
from open_notebook.domain.notebook import Asset, Source
from open_notebook.domain.transformation import Transformation
from open_notebook.domain.video_vision import merge_transcript_with_visual
from open_notebook.graphs.transformation import graph as transform_graph
from open_notebook.utils.runtime_capabilities import engine_runtime_missing
from open_notebook.utils.video_frames import extract_frames, ffprobe_duration

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

VISION_SEGMENT_SIZE = 6


def _looks_like_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _VIDEO_EXTENSIONS


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
                parts.append(f"### {seg_start:.0f}s\n\n{description}")
            return "\n\n".join(parts) or None
        finally:
            _cleanup_frames(frames)
    except Exception as e:
        logger.warning(f"Vision pass failed for {video_path}: {e}")
        return None


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

    processed = await extract_content(
        url=content_state.get("url"),
        file_path=content_state.get("file_path"),
        content=content_state.get("content"),
        config=config,
    )

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

    if not processed.content or not processed.content.strip():
        url = content_state.get("url") or ""
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
            else:
                raise ValueError(
                    "Could not extract content from this YouTube video. "
                    "No transcript or subtitles are available and audio "
                    "transcription failed. Try configuring a Speech-to-Text "
                    "model in Settings to transcribe the audio instead."
                )
        else:
            raise ValueError(
                "Could not extract any text content from this source. "
                "The content may be empty, inaccessible, or in an unsupported format."
            )

    # Vision pass: watch video frames with a dedicated vision model and merge
    # the visual notes into the transcript. Never raises — any failure keeps
    # the transcript-only source.
    if video_vision and vision_available():
        video_path: Optional[str] = None
        temp_video = False
        try:
            file_path = content_state.get("file_path")
            if file_path and _looks_like_video(file_path):
                video_path = file_path
            else:
                url = content_state.get("url") or ""
                if url and ("youtube.com" in url or "youtu.be" in url):
                    video_path = await _run_blocking(download_youtube_video, url)
                    temp_video = video_path is not None
            if video_path:
                visual = await vision_enhance(video_path, processed.content)
                if visual:
                    processed = ExtractionOutput(
                        title=processed.title,
                        content=merge_transcript_with_visual(processed.content, visual),
                        metadata=dict(processed.metadata or {}),
                    )
        except Exception:
            logger.warning(
                "vision pass failed; source kept transcript-only", exc_info=True
            )
        finally:
            if temp_video and video_path:
                try:
                    os.unlink(video_path)
                except OSError:
                    pass

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
