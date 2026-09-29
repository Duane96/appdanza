"""Small allowlist for existing formatted academy headings, never arbitrary HTML."""
import re
from html.parser import HTMLParser
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


class HeadingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag not in ('br', 'b', 'strong', 'em', 'span'):
            return
        style = dict(attrs).get('style', '')
        match = re.fullmatch(r'\s*color:\s*(#[a-fA-F0-9]{3,8}|var\(--[a-zA-Z0-9-]+\))\s*;?\s*', style)
        self.parts.append('<'+tag+(f' style="color:{match[1]}"' if tag == 'span' and match else '')+'>')

    def handle_endtag(self, tag):
        if tag in ('b', 'strong', 'em', 'span'):
            self.parts.append('</'+tag+'>')

    def handle_data(self, data):
        self.parts.append(str(escape(data)))


@register.filter
def safe_heading(value):
    parser = HeadingParser()
    parser.feed(str(value or ''))
    parser.close()
    return mark_safe(''.join(parser.parts))
