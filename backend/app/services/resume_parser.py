import io
from pathlib import Path

from pypdf import PdfReader


ALLOWED_EXTENSIONS = {".pdf", ".txt"}
MAX_RESUME_BYTES = 5 * 1024 * 1024


def validate_resume_file(filename: str, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Only PDF and TXT resumes are supported.")
    if len(content) > MAX_RESUME_BYTES:
        raise ValueError("Resume must be 5 MB or smaller.")
    if not content:
        raise ValueError("Uploaded file is empty.")


def extract_text_from_resume(filename: str, content: bytes) -> str:
    validate_resume_file(filename, content)
    suffix = Path(filename).suffix.lower()

    if suffix == ".txt":
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return content.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not read text resume encoding.")

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("Could not extract text from PDF. Try a text-based PDF or TXT file.")
    return text
