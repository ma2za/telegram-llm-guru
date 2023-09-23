import asyncio
import io
import logging
import os
import random
from collections.abc import AsyncIterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import List

import PIL.Image as Image
from geopy import Nominatim
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image as ReportImage, ParagraphAndImage
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak

__all__ = ["write"]

from telegram_smart_bots.shared.db.minio_storage import minio_manager

logger = logging.getLogger(__name__)

styles = getSampleStyleSheet()
sign_style = styles["Heading3"]
sign_style.fontName = "Courier"

body_style = styles["BodyText"]
body_style.fontName = "Courier"
geolocator = Nominatim(user_agent=os.getenv("BOT_NAME"))


def build_locations_sign(locations: List) -> str:
    cities = []
    for loc in locations:
        address = geolocator.reverse(loc).raw.get("address")
        city = address.get("city", address.get("suburb"))
        if len(cities) == 0 or cities[-1] != city:
            cities.append(city)
    if len(cities) == 0:
        return ""
    elif len(cities) == 1:
        result = cities[0]
    else:
        result = f"{cities[0]} to {cities[-1]}"
        via = ", ".join(cities[1:-1])
        if via:
            result = f"{result}, via {via}"
    return f"{result}, "


@lru_cache
def evenly_split_text(text: str, n_segments: int) -> List[str]:
    segments = []
    current_segment = ""
    max_segment_length = len(text) / n_segments
    for sentence in text.split("."):
        if len(sentence) == 0:
            continue
        if len(current_segment) + len(sentence) + 1 <= max_segment_length:
            current_segment += sentence + "."
        else:
            segments.append(current_segment.strip())
            current_segment = sentence + "."
    if current_segment:
        segments.append(current_segment.strip())
    return segments


# DO NOT REMOVE doc PARAMETER
def draw_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.beige)
    canvas.rect(0, 0, A5[0], A5[1], fill=True, stroke=False)
    canvas.restoreState()


async def create_photos(entry_date: str, user_id) -> list:
    photos = []
    images = minio_manager.get_objects(user_id, entry_date)

    for img_k, img_v in images:
        image_path = f".tmp/{Path(img_k).name}"
        image = Image.open(io.BytesIO(img_v))
        image.save(image_path)

        img = ReportImage(image_path)
        size_perc = random.uniform(0.3, 0.45)
        img.drawHeight, img.drawWidth = (
            A5[0] * size_perc
        ) * img.drawHeight / img.drawWidth, A5[0] * size_perc

        photos.append(img)
        try:
            os.remove(image_path)
        except OSError as e:
            print(f"Error: {e}")
    return photos


async def write(output_pdf: str, entries: AsyncIterable, user_id: int):
    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=A5,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    story = []
    first_page = True
    async for k, jrnl_entry in entries:
        if not first_page:
            story.append(PageBreak())

        sign = build_locations_sign(
            [
                e.content
                for e in jrnl_entry
                if e.additional_kwargs.get("type") == "location"
            ]
        )
        # TODO change date format to ordinal
        sign += f"{datetime.strptime(k, '%Y-%m-%d').strftime('%A, %B %-d, %Y')}\n\n\n"
        story.append(Paragraph(sign, sign_style))
        # TODO check strings sorting
        photos = await create_photos(k, user_id)
        text = "\n\n".join(
            [e.content for e in jrnl_entry if e.additional_kwargs.get("type") == "text"]
        )
        segments = evenly_split_text(text, max(1, len(photos)))
        if len(segments):
            x = 0
            for j, entry in enumerate(segments):
                side = "left" if random.randint(0, 2) == 0 else "right"
                p = Paragraph(entry, body_style)
                if x < len(photos):
                    story.append(
                        ParagraphAndImage(
                            p,
                            photos[x],
                            xpad=10,
                            ypad=3,
                            side=side,
                        )
                    )
                    x += 1
                else:
                    story.append(p)
        else:
            for photo in photos:
                story.append(photo)
        first_page = False
        await asyncio.sleep(0.01)
    doc.build(story, onFirstPage=draw_background, onLaterPages=draw_background)
    return "😄"
