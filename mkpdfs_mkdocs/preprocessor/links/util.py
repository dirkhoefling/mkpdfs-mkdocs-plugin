import os

from weasyprint import urls
from bs4 import BeautifulSoup


# File extensions that should NOT be treated as documentation links
NON_DOC_EXTENSIONS = {'.xls', '.xlsx', '.pdf', '.doc', '.docx', '.zip', '.png', '.jpg', '.jpeg', '.gif', '.svg'}

# check if href is relative --
# if it is relative it *should* be an html that generates a PDF doc
def is_doc(href: str):
    if urls.url_is_absolute(href):
        return False
    if os.path.isabs(href):
        return False

    # Check if the href points to a non-documentation file (downloads, images, etc.)
    # Extract the path part before any anchor
    path_part = href.split('#')[0].split('?')[0].lower()
    for ext in NON_DOC_EXTENSIONS:
        if path_part.endswith(ext):
            return False

    return True


def rel_pdf_href(href: str):
    head, tail = os.path.split(href)
    filename, _ = os.path.splitext(tail)

    internal = href.startswith('#')
    if not is_doc(href) or internal:
        return href

    return urls.iri_to_uri(os.path.join(head, filename + '.pdf'))

def abs_asset_href(href: str, base_url: str):
    if urls.url_is_absolute(href) or os.path.isabs(href):
        return href

    return urls.iri_to_uri(urls.urljoin(base_url, href))

# Replace SVG with PNG for PDF generation (only if PNG exists in _svg_to_png subfolder - SVG 2.0 not supported by WeasyPrint)
def replace_svg_with_png(src: str, base_url: str = None):
    if src.lower().endswith('.svg'):
        # PNG is in _svg_to_png subfolder: image.svg -> _svg_to_png/image.png
        src_dir = os.path.dirname(src)
        src_name = os.path.basename(src)
        png_name = src_name[:-4] + '.png'
        png_src = os.path.join(src_dir, '_svg_to_png', png_name) if src_dir else '_svg_to_png/' + png_name

        # Check if PNG file exists (for SVG 2.0 files that were converted)
        if base_url:
            # Try to resolve the full path
            from urllib.parse import urlparse, unquote
            parsed = urlparse(base_url)
            if parsed.scheme == 'file':
                base_path = unquote(parsed.path)
                # On Windows, remove leading slash from /C:/...
                if len(base_path) > 2 and base_path[0] == '/' and base_path[2] == ':':
                    base_path = base_path[1:]
                png_path = os.path.join(os.path.dirname(base_path), png_src.lstrip('/'))
                png_path = os.path.normpath(png_path)
                if os.path.exists(png_path):
                    return png_src
        return src  # Keep SVG if no PNG exists
    return src


# makes all relative asset links absolute
def replace_asset_hrefs(soup: BeautifulSoup, base_url: str):
    for link in soup.find_all('link', href=True):
        link['href'] = abs_asset_href(link['href'], base_url)

    for asset in soup.find_all(src=True):
        # Replace SVG with PNG for better PDF compatibility (only if PNG exists)
        asset['src'] = replace_svg_with_png(asset['src'], base_url)
        asset['src'] = abs_asset_href(asset['src'], base_url)

    return soup


def normalize_href(href: str, rel_url: str):
    """
    Normalize href to site root
    foo/bar/baz/../../index.html -> foo/index.html
    :param href:
    :param rel_url:
    :return:

    >>> normalize_href("../../index.html", "foo/bar/baz/page.html")
    'foo/index.html'

    >>> normalize_href("page2.html#abcd", "foo/bar/baz/page.html")
    'foo/bar/baz/page2.html#abcd'

    >>> normalize_href("#section", "foo/bar/baz/page.html")
    'foo/bar/baz/page.html#section'

    >>> normalize_href("/index.html", "foo/bar/baz/page.html")
    '/index.html'

    >>> normalize_href("http://example.org/index.html", "foo/bar/baz/page.html")
    'http://example.org/index.html'
    """
    if not is_doc(href):
        return href
    if href.startswith("#"):
        return rel_url + href
    rel_dir = os.path.dirname(rel_url)
    return os.path.normpath(os.path.join(rel_dir, href))


def get_body_id(url: str):
    return '{}:'.format(url)