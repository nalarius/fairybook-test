"""Story generation, export, and persistence orchestration."""
from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from gcs_storage import upload_html_to_gcs

HTML_EXPORT_DIR = "html_exports"
HTML_EXPORT_PATH = Path(HTML_EXPORT_DIR)


@dataclass(slots=True)
class StagePayload:
    stage_name: str
    card_name: str | None
    card_prompt: str | None
    paragraphs: Sequence[str]
    image_bytes: bytes | None
    image_mime: str
    image_style_name: str | None = None


@dataclass(slots=True)
class StoryBundle:
    title: str
    stages: Sequence[StagePayload]
    synopsis: str | None
    protagonist: str | None
    cover: Mapping[str, Any] | None
    story_type_name: str
    age: str
    topic: str | None


@dataclass(slots=True)
class ExportResult:
    local_path: str
    gcs_object: str | None = None
    gcs_url: str | None = None


def list_html_exports() -> list[Path]:
    try:
        files = [p for p in HTML_EXPORT_PATH.glob("*.html") if p.is_file()]
        return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
    except Exception:
        return []


def _slugify_filename(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    slug = value.strip("-")
    return slug or "story"


def _build_story_html_document(
    *,
    title: str,
    age: str,
    topic: str,
    story_type: str,
    stages: Sequence[Mapping[str, Any]],
    cover: Mapping[str, Any] | None = None,
    author: str | None = None,
) -> str:
    escaped_title = html.escape(title)
    escaped_author = html.escape(author) if author else ""

    cover_section = ""
    if cover and cover.get("image_data_uri"):
        cover_section = (
            "    <section class=\"cover stage\">\n"
            "        <figure>\n"
            f"            <img src=\"{cover.get('image_data_uri')}\" alt=\"{escaped_title} 표지\" />\n"
            "        </figure>\n"
            "    </section>\n"
        )

    stage_sections: list[str] = []
    for stage in stages:
        image_data_uri = stage.get("image_data_uri") or ""
        paragraphs = stage.get("paragraphs") or []

        paragraphs_html = "\n".join(
            f"            <p>{html.escape(paragraph)}</p>" for paragraph in paragraphs
        ) or "            <p>(본문이 없습니다)</p>"

        image_section = (
            "        <figure>\n"
            f"            <img src=\"{image_data_uri}\" alt=\"{escaped_title} 삽화\" />\n"
            "        </figure>\n"
        ) if image_data_uri else ""

        section_html = (
            "    <section class=\"stage\">\n"
            f"{image_section}"
            f"{paragraphs_html}\n"
            "    </section>\n"
        )
        stage_sections.append(section_html)

    stages_html = "".join(stage_sections)

    author_block = (
        f"        <p class=\"meta\">작성자: {escaped_author}</p>\n" if escaped_author else ""
    )

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "    <meta charset=\"utf-8\" />\n"
        f"    <title>{escaped_title}</title>\n"
        "    <style>\n"
        "        body { font-family: 'Noto Sans KR', sans-serif; margin: 2rem; background: #faf7f2; color: #2c2c2c; }\n"
        "        header { margin-bottom: 2.5rem; }\n"
        "        h1 { font-size: 2rem; margin-bottom: 0.5rem; }\n"
        "        .meta { color: #555; font-size: 0.95rem; margin-bottom: 0.5rem; }\n"
        "        .cover { margin-bottom: 3rem; }\n"
        "        .stage { margin-bottom: 3rem; padding-bottom: 2rem; border-bottom: 1px solid rgba(0,0,0,0.08); }\n"
        "        .stage:last-of-type { border-bottom: none; }\n"
        "        figure { text-align: center; margin: 1.5rem auto; }\n"
        "        figure img { max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 12px 36px rgba(0,0,0,0.12); }\n"
        "        figcaption { font-size: 0.9rem; color: #666; margin-top: 0.5rem; }\n"
        "        p { line-height: 1.65; font-size: 1.05rem; margin-bottom: 1rem; }\n"
        "    </style>\n"
        "</head>\n"
        "<body>\n"
        "    <header>\n"
        f"        <h1>{escaped_title}</h1>\n"
        f"{author_block}"
        "    </header>\n"
        f"{cover_section}{stages_html}"
        "</body>\n"
        "</html>\n"
    )


def export_story_to_html(
    *,
    bundle: StoryBundle,
    author: str | None = None,
    use_remote_exports: bool = False,
) -> ExportResult:
    HTML_EXPORT_PATH.mkdir(parents=True, exist_ok=True)

    normalized_stages: list[dict[str, Any]] = []
    for stage in bundle.stages:
        paragraphs = [str(p).strip() for p in stage.paragraphs if str(p).strip()]
        image_data_uri = None
        if stage.image_bytes:
            encoded = base64.b64encode(stage.image_bytes).decode("utf-8")
            image_data_uri = f"data:{stage.image_mime};base64,{encoded}"

        normalized_stages.append(
            {
                "stage_name": stage.stage_name,
                "card_name": stage.card_name,
                "card_prompt": stage.card_prompt,
                "paragraphs": paragraphs,
                "image_data_uri": image_data_uri,
                "image_style_name": stage.image_style_name,
            }
        )

    cover_section = None
    cover = bundle.cover or None
    if cover and cover.get("image_bytes"):
        cover_bytes = cover.get("image_bytes")
        image_mime = cover.get("image_mime") or "image/png"
        encoded = base64.b64encode(cover_bytes).decode("utf-8")
        cover_section = {
            "image_data_uri": f"data:{image_mime};base64,{encoded}",
            "style_name": cover.get("style_name"),
        }

    safe_title = bundle.title.strip() or "동화"
    html_doc = _build_story_html_document(
        title=safe_title,
        age=bundle.age,
        topic=bundle.topic or "",
        story_type=bundle.story_type_name,
        stages=normalized_stages,
        cover=cover_section,
        author=author or "",
    )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify_filename(safe_title)
    filename = f"{timestamp}_{slug}.html"
    export_path = HTML_EXPORT_PATH / filename

    export_path.write_text(html_doc, encoding="utf-8")

    gcs_object = None
    gcs_url = None
    if use_remote_exports:
        upload_result = upload_html_to_gcs(html_doc, filename)
        if upload_result:
            gcs_object, gcs_url = upload_result

    return ExportResult(str(export_path), gcs_object=gcs_object, gcs_url=gcs_url)


__all__ = [
    "StagePayload",
    "StoryBundle",
    "ExportResult",
    "export_story_to_html",
    "list_html_exports",
    "HTML_EXPORT_PATH",
]
