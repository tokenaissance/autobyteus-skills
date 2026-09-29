"""HTML cleanup modes shared by all public adapters."""

from bs4 import BeautifulSoup, Comment


def _remove_empty_tags(element) -> bool:
    if isinstance(element, Comment):
        return True
    if isinstance(element, str) and not element.strip():
        return True
    if hasattr(element, "contents"):
        for child in list(element.contents):
            if _remove_empty_tags(child):
                child.extract()
    if hasattr(element, "get_text"):
        return len(element.get_text(strip=True)) == 0 and getattr(element, "name", None) not in {"br", "hr", "img"}
    return False


def clean_html(html_text: str, mode: str) -> str:
    if mode == "raw":
        return html_text

    soup = BeautifulSoup(html_text, "html.parser")
    if mode == "text":
        return " ".join(soup.stripped_strings)

    for script in soup(["script", "style"]):
        script.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    content = soup.body or soup
    for tag in content.find_all(True):
        tag.attrs = {}
    _remove_empty_tags(content)
    return str(content)
