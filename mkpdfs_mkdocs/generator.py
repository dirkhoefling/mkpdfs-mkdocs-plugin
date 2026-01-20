import logging
import os
import sys
from html import unescape
from uuid import uuid4

from weasyprint import HTML, urls, CSS
from bs4 import BeautifulSoup
from weasyprint.text.fonts import FontConfiguration

from datetime import datetime
from mkpdfs_mkdocs.utils import gen_address
from .utils import is_external
from mkpdfs_mkdocs.preprocessor import get_separate as prep_separate, get_combined as prep_combined
from mkpdfs_mkdocs.preprocessor import adjust_heading_levels
from mkpdfs_mkdocs.preprocessor import nest_heading_bookmarks
from mkpdfs_mkdocs.preprocessor import remove_header_links
from mkpdfs_mkdocs.preprocessor import remove_material_header_icons

log = logging.getLogger(__name__)


class Generator(object):

    def __init__(self):
        self.config = None
        self.design = None
        self.mkdconfig = None
        self.nav = None
        self.title = None
        self.logger = logging.getLogger('mkdocs.mkpdfs')
        self.generate = True
        self._articles = {}
        self._page_order = []
        self._page_nesting = {}
        self._base_urls = {}
        self._toc = None
        self._index_to_chapter = {}  # Maps index.md URL to chapter UUID
        self._skipped_sections = set()  # Section titles to skip in TOC
        self.html = BeautifulSoup('<html><head></head>\
        <body></body></html>',
                                  'html.parser')
        self.dir = os.path.dirname(os.path.realpath(__file__))
        self.design = os.path.join(self.dir, 'design/report.css')

    def set_config(self, local, config):
        self.config = local
        if self.config['design']:
            css_file = os.path.join(os.getcwd(), self.config['design'])
            if not os.path.isfile(css_file):
                sys.exit('The file {} specified for design has not \
                been found.'.format(css_file))
            self.design = css_file
        self.title = config['site_name']
        copyright_text = config.get('copyright') or ''
        self.config['copyright'] = copyright_text.replace('@YYYY', str(datetime.now().year))
        self.mkdconfig = config

    def write(self):
        if not self.generate:
            self.logger.log(msg='Unable to generate the PDF Version (See Mkpdfs doc)',
                            level=logging.WARNING, )
            return
        self.gen_articles()
        font_config = FontConfiguration()
        self.add_head()
        pdf_path = os.path.join(self.mkdconfig['site_dir'],
                                self.config['output_path'])
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

        if self.config['export_combinedHTML']:
            htmlcontent = str(self.html)
            text_file = open(pdf_path + ".html", "w")
            text_file.write(htmlcontent)
            text_file.close()

        html = HTML(string=str(self.html)).write_pdf(pdf_path,
                                                     font_config=font_config)
        self.logger.log(msg='The PDF version of the documentation has been generated.', level=logging.INFO, )

    def add_nav(self, nav):
        self.nav = nav
        for p in nav:
            self.add_to_order(p)

    def add_to_order(self, page, level=1):
        if page.is_page and page.meta and 'pdf' in page.meta and not page.meta['pdf']:
            return
        if page.is_page:
            self._page_nesting[page.file.url] = level - 1
            self._page_order.append(page.file.url)
        elif page.children:
            uuid = str(uuid4())
            self._page_order.append(uuid)
            title = self.html.new_tag('h1',
                                      id='{}-title'.format(uuid),
                                      **{'class': 'section_title',
                                          # See also nest_heading_bookmarks()
                                         'style': 'bookmark-level:{}'.format(level)}
                                      )
            title.append(unescape(page.title))
            article = self.html.new_tag('article',
                                        id='{}'.format(uuid),
                                        **{'class': 'chapter'}
                                        )
            article.append(title)
            self._articles[uuid] = article
            # Track index.md to chapter mapping for pdf_chapter support
            for child in page.children:
                if child.is_page and hasattr(child, 'file') and child.file.name == 'index':
                    self._index_to_chapter[child.file.src_path] = (uuid, page.title)
                    self.logger.info(f"Tracked chapter mapping: {child.file.src_path} -> {uuid} (title: {page.title})")
                    break
            for child in page.children:
                self.add_to_order(child, level=level + 1)

    def remove_from_order(self, item):
        return

    def add_article(self, content, page, base_url):
        if not self.generate:
            return None
        self._base_urls[page.file.url] = base_url
        soup = BeautifulSoup(content, 'html.parser')
        url = page.url.split('.')[0]
        article = soup.find('article')
        if not article:
            article = self.html.new_tag('article')
            eld = soup.find('div', **{'role': 'main'})
            article.append(eld)
            article.div['class'] = article.div['role'] = None

        if not article:
            self.generate = False
            return None
        if self.mkdconfig['theme'].name == 'material':
            article = remove_material_header_icons(article)
        article = prep_combined(article, base_url, page.file.url)
        article = remove_header_links(article)
        nesting_level = self._page_nesting.get(page.file.url, 0)
        article = nest_heading_bookmarks(article, nesting_level)
        # Optionally adjust visual heading levels based on nesting depth
        if self.config.get('heading_shift', False):
            # Non-index pages get an extra level shift (they're subpages of index.md)
            shift_level = nesting_level
            if page.file.name != 'index':
                shift_level += 1
            self.logger.info(f"heading_shift: {page.file.src_path} nesting={nesting_level} shift={shift_level}")
            article = adjust_heading_levels(article, shift_level)
        if page.meta and 'pdf' in page.meta and not page.meta['pdf']:
            # print(page.meta)
            return self.get_path_to_pdf(page.file.dest_path)
        # Check if this index.md has pdf_chapter: false - if so, remove the chapter article
        if page.meta and 'pdf_chapter' in page.meta and not page.meta['pdf_chapter']:
            self.logger.info(f"Found pdf_chapter: false in {page.file.src_path}")
            if page.file.src_path in self._index_to_chapter:
                chapter_uuid, section_title = self._index_to_chapter[page.file.src_path]
                self.logger.info(f"Removing chapter {chapter_uuid} for {page.file.src_path} (section: {section_title})")
                if chapter_uuid in self._articles:
                    del self._articles[chapter_uuid]
                if chapter_uuid in self._page_order:
                    self._page_order.remove(chapter_uuid)
                # Also skip this section in TOC
                self._skipped_sections.add(section_title)
            else:
                self.logger.info(f"No chapter mapping found for {page.file.src_path}")
        self._articles[page.file.url] = article
        return self.get_path_to_pdf(page.file.dest_path)

    def add_head(self):
        lines = ['<title>{}</title>'.format(self.title)]
        for key, val in (
                ("author", self.config['author'] or self.mkdconfig['site_author']),
                ("description", self.mkdconfig['site_description']),
        ):
            if val:
                lines.append('<meta name="{}" content="{}">'.format(key, val))
        for css in (self.design,):
            if css:
                css_tmpl = '<link rel="stylesheet" href="{}" type="text/css">'
                lines.append(css_tmpl.format(urls.path2url(css)))
        head = BeautifulSoup('<head>' + '\n'.join(lines) + '</head>', 'html.parser')
        self.html.head.replace_with(head)

    def add_tocs(self):
        title = self.html.new_tag('h1', id='toc-title')
        title.insert(0, self.config['toc_title'])
        self._toc = self.html.new_tag('article', id='contents')
        self._toc.insert(0, title)
        for n in self.nav:
            if n.is_page and n.meta and 'pdf' in n.meta \
                    and not n.meta['pdf']:
                continue
            if hasattr(n, 'url') and is_external(n.url):
                # Skip toc generation for external links
                continue
            h3 = self.html.new_tag('h3')
            h3.insert(0, unescape(n.title))
            self._toc.append(h3)
            if n.is_page:
                ptoc = self._gen_toc_page(n.file.url, n.toc)
                self._toc.append(ptoc)
            else:
                self._gen_toc_section(n)
        self.html.body.append(self._toc)

    def add_cover(self):
        a = self.html.new_tag('article', id='doc-cover')
        title = self.html.new_tag('h1', id='doc-title')
        title.insert(0, self.title)
        a.insert(0, title)
        a.append(gen_address(self.config))
        self.html.body.append(a)

    def gen_articles(self):
        self.add_cover()
        if self.config['toc_position'] == 'pre':
            self.add_tocs()
        for url in self._page_order:
            if url in self._articles:
                self.html.body.append(self._articles[url])
        if self.config['toc_position'] == 'post':
            self.add_tocs()

    def get_path_to_pdf(self, start):
        return os.path.relpath(self.config['output_path'],
                               os.path.dirname(start))

    def _gen_toc_section(self, section, is_skipped_section=False):
        if section.children:  # External Links do not have children
            # Check if this section is marked with pdf_chapter: false
            section_is_skipped = section.title in self._skipped_sections
            section_ul = None
            for p in section.children:
                if p.is_page and p.meta and 'pdf' \
                        in p.meta and not p.meta['pdf']:
                    continue
                if p.is_section:
                    # Skip section header if marked with pdf_chapter: false
                    if p.title not in self._skipped_sections:
                        h3 = self.html.new_tag('h3')
                        h3.insert(0, unescape(p.title))
                        self._toc.append(h3)
                    self._gen_toc_section(p, p.title in self._skipped_sections)
                    continue
                if not hasattr(p, 'file'):
                    # Skip external links
                    continue
                # Handle index.md - its TOC items go directly into section
                if p.file.name == 'index':
                    stoc = self._gen_toc_for_index(p.file.url, p)
                    if stoc:
                        self._toc.append(stoc)
                        # Get the ul from the stoc for adding non-index pages
                        section_ul = stoc.find('ul')
                elif section_is_skipped:
                    # For skipped sections (pdf_chapter: false), add TOC items directly without page title
                    items = self._gen_toc_for_subpage(p.file.url, p)
                    if items:
                        if section_ul is None:
                            section_ul = self.html.new_tag('ul')
                            self._toc.append(section_ul)
                        for item in items:
                            section_ul.append(item)
                else:
                    # Normal sections: show page title as header with TOC items
                    stoc = self._gen_toc_for_page(p.file.url, p)
                    child = self.html.new_tag('div')
                    child.append(stoc)
                    self._toc.append(child)

    def _gen_children(self, url, children):
        ul = self.html.new_tag('ul')
        for child in children:
            a = self.html.new_tag('a', href=child.url)
            a.insert(0, unescape(child.title))
            li = self.html.new_tag('li')
            li.append(a)
            if child.children:
                sub = self._gen_children(url, child.children)
                li.append(sub)
            ul.append(li)
        return ul

    def _gen_toc_for_page(self, url, p):
        """Generate TOC for normal pages - shows page title as h4 header with TOC items"""
        div = self.html.new_tag('div')
        menu = self.html.new_tag('div')
        h4 = self.html.new_tag('h4')
        a = self.html.new_tag('a', href='#')
        a.insert(0, unescape(p.title))
        h4.append(a)
        menu.append(h4)
        ul = self.html.new_tag('ul')
        if p.toc:
            for child in p.toc.items:
                a = self.html.new_tag('a', href=child.url)
                a.insert(0, unescape(child.title))
                li = self.html.new_tag('li')
                li.append(a)
                if child.title == p.title:
                    li = self.html.new_tag('div')
                if child.children:
                    sub = self._gen_children(url, child.children)
                    li.append(sub)
                ul.append(li)
            if len(p.toc.items) > 0:
                menu.append(ul)
        div.append(menu)
        div = prep_combined(div, self._base_urls[url], url)
        return div.find('div')

    def _gen_toc_for_index(self, url, p):
        """Generate TOC for index.md - returns div with h4 title and ul of TOC items"""
        div = self.html.new_tag('div')
        menu = self.html.new_tag('div')
        h4 = self.html.new_tag('h4')
        a = self.html.new_tag('a', href='#')
        a.insert(0, unescape(p.title))
        h4.append(a)
        menu.append(h4)
        ul = self.html.new_tag('ul')
        if p.toc:
            for child in p.toc.items:
                # If this is the page title (h1), add its children directly to ul
                if child.title == p.title:
                    if child.children:
                        for subchild in child.children:
                            sub_a = self.html.new_tag('a', href=subchild.url)
                            sub_a.insert(0, unescape(subchild.title))
                            sub_li = self.html.new_tag('li')
                            sub_li.append(sub_a)
                            if subchild.children:
                                sub_sub = self._gen_children(url, subchild.children)
                                sub_li.append(sub_sub)
                            ul.append(sub_li)
                    continue
                # Normal TOC item
                a = self.html.new_tag('a', href=child.url)
                a.insert(0, unescape(child.title))
                li = self.html.new_tag('li')
                li.append(a)
                if child.children:
                    sub = self._gen_children(url, child.children)
                    li.append(sub)
                ul.append(li)
            if len(ul.contents) > 0:
                menu.append(ul)
        div.append(menu)
        div = prep_combined(div, self._base_urls[url], url)
        return div.find('div')

    def _gen_toc_for_subpage(self, url, p):
        """Generate TOC for non-index pages - returns list of li items from the page's TOC"""
        if not p.toc or len(p.toc.items) == 0:
            return []
        # Build a temporary div to hold items for URL transformation
        div = self.html.new_tag('div')
        ul = self.html.new_tag('ul')
        for child in p.toc.items:
            if child.title == p.title:
                # Skip the page title itself in the TOC
                continue
            li = self.html.new_tag('li')
            a = self.html.new_tag('a', href=child.url)
            a.insert(0, unescape(child.title))
            li.append(a)
            if child.children:
                sub = self._gen_children(url, child.children)
                li.append(sub)
            ul.append(li)
        div.append(ul)
        # Transform URLs through prep_combined
        div = prep_combined(div, self._base_urls.get(url, ''), url)
        # Extract and return the li items
        transformed_ul = div.find('ul')
        if transformed_ul:
            return list(transformed_ul.children)
        return []

    def _gen_toc_page(self, url, toc):
        div = self.html.new_tag('div')
        menu = self.html.new_tag('ul')
        for item in toc.items:
            li = self.html.new_tag('li')
            a = self.html.new_tag('a', href=item.url)
            a.append(unescape(item.title))
            li.append(a)
            menu.append(li)
            if item.children:
                child = self._gen_children(url, item.children)
                menu.append(child)
        div.append(menu)
        div = prep_combined(div, self._base_urls[url], url)
        return div.find('ul')
