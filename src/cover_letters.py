"""Cover letter template loading."""

from pathlib import Path

import frontmatter

TEMPLATES_DIR = Path(__file__).parent.parent / "data" / "cover_letter_templates"


def list_templates() -> list[dict]:
    """Return name + description for every template file."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.md")):
        post = frontmatter.load(str(path))
        templates.append({
            "name": post.get("name", path.stem),
            "description": post.get("description", ""),
        })
    return templates


def load_template(name: str) -> str | None:
    """Return the body of a template by slug name, or None if not found."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / f"{name}.md"
    if not path.exists():
        return None
    post = frontmatter.load(str(path))
    return post.content
