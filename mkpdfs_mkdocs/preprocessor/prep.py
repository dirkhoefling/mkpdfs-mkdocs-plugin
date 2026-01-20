import os

from .links import transform_href, transform_id, get_body_id, replace_asset_hrefs, rel_pdf_href

from weasyprint import urls
from bs4 import BeautifulSoup

def get_combined(soup: BeautifulSoup, base_url: str, rel_url: str):
    # Add explicit anchor tags for headings with ids (for MkDocs Material { #anchor } syntax)
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        if heading.get('id'):
            # Create an anchor element before the heading for better PDF anchor resolution
            # Use BeautifulSoup to create the new tag since soup is actually a Tag element
            anchor_soup = BeautifulSoup('<a></a>', 'html.parser')
            anchor = anchor_soup.a
            anchor['id'] = heading['id']
            anchor['name'] = heading['id']
            heading.insert_before(anchor)

    # Transform all id attributes
    for el in soup.find_all(id=True):
        el['id'] = transform_id(el['id'], rel_url)

    # Also transform name attributes on anchor elements
    for a in soup.find_all('a', attrs={'name': True}):
        a['name'] = transform_id(a['name'], rel_url)

    for a in soup.find_all('a', href=True):
        if urls.url_is_absolute(a['href']) or os.path.isabs(a['href']):
            a['class'] = 'external-link'
            continue

        a['href'] = transform_href(a['href'], rel_url)

    soup.attrs['id'] = get_body_id(rel_url)
    soup = replace_asset_hrefs(soup, base_url)
    return soup

def get_separate(soup: BeautifulSoup, base_url: str):
    # transforms all relative hrefs pointing to other html docs
    # into relative pdf hrefs
    for a in soup.find_all('a', href=True):
        a['href'] = rel_pdf_href(a['href'])

    soup = replace_asset_hrefs(soup, base_url)
    return soup

def remove_material_header_icons(soup: BeautifulSoup):
    """Removes links added to article headers by material theme such as the
    page edit link/url (pencil icon)."""
    # see https://github.com/squidfunk/mkdocs-material/issues/1920
    # for justification of why this CSS class is used
    for a in soup.find_all('a', **{'class': 'md-content__button'}):
        a.decompose()
    return soup

def remove_header_links(soup: BeautifulSoup):
    for a in soup.find_all('a', **{'class': 'headerlink'}):
        a.decompose()
    return soup

def nest_heading_bookmarks(soup: BeautifulSoup, inc: int):
    """Ensure titles & subheadings of pages are properly nested as bookmarks.

    So that while a page's titles always starts as <h1>,
    when seen in the PDF index, all page headings will be nested according
    to the page's nesting under sections & subsections.
    """
    if not inc:
        return soup
    assert isinstance(inc, int) and inc > 0
    for i in range(6, 0, -1):
        # For each level of heading, add an inline CSS style that sets the
        # bookmark-level to the heading level + `inc`.
        for h in soup.find_all('h{}'.format(i)):
            h['style'] = 'bookmark-level:{}'.format(i + inc)
    return soup


def adjust_heading_levels(soup: BeautifulSoup, inc: int):
    """Adjust heading levels based on page nesting depth.

    Transforms heading tags (h1->h2, h2->h3, etc.) based on the page's
    nesting level in the navigation structure. This ensures proper
    visual hierarchy in the combined PDF document.

    Args:
        soup: BeautifulSoup element containing the page content
        inc: Number of levels to shift headings down (e.g., 1 means h1->h2)

    Returns:
        Modified soup with adjusted heading levels
    """
    if not inc:
        return soup
    assert isinstance(inc, int) and inc > 0

    # Process from h6 down to h1 to avoid conflicts
    # (e.g., don't convert h1->h2 before converting h2->h3)
    for i in range(6, 0, -1):
        new_level = min(i + inc, 6)  # Cap at h6
        for h in soup.find_all('h{}'.format(i)):
            h.name = 'h{}'.format(new_level)
    return soup
