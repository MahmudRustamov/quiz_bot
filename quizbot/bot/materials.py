"""Deliver complete passages without exceeding Telegram's message limit."""


def split_material(text: str, limit: int = 3500) -> list[str]:
    chunks = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        boundary = remaining.rfind("\n\n", 0, limit + 1)
        if boundary < limit // 3:
            boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary <= 0:
            boundary = limit
        chunks.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()
    return chunks


async def send_materials(message, materials: list[dict]) -> None:
    for material in materials:
        pages = ", ".join(str(p) for p in material["source_pages"])
        heading = f"📖 {material['title']}"
        if pages:
            heading += f" · PDF: {pages}-bet"
        for chunk in split_material(heading + "\n\n" + material["text"]):
            await message.answer(chunk)
