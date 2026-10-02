import html
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP


TTML_NAMESPACE = 'http://www.w3.org/ns/ttml'
TTS_NAMESPACE = 'http://www.w3.org/ns/ttml#styling'
XML_NAMESPACE = 'http://www.w3.org/XML/1998/namespace'


def _local_name(tag):
    return tag.rsplit('}', 1)[-1]


def _style_id(element):
    return element.get(f'{{{XML_NAMESPACE}}}id')


def _resolve_style(style_id, styles, cache, resolving=None):
    if style_id in cache:
        return cache[style_id]
    style = styles.get(style_id)
    if style is None:
        return {}

    resolving = resolving or set()
    if style_id in resolving:
        return {}
    resolving.add(style_id)

    resolved = {}
    for parent_id in style.get('style', '').split():
        resolved.update(_resolve_style(parent_id, styles, cache, resolving))
    for name, value in style.attrib.items():
        if name.startswith(f'{{{TTS_NAMESPACE}}}'):
            resolved[_local_name(name)] = value

    resolving.remove(style_id)
    cache[style_id] = resolved
    return resolved


def _element_color(element, inherited_color, styles, cache):
    color = inherited_color
    for style_id in element.get('style', '').split():
        color = _resolve_style(style_id, styles, cache).get('color', color)
    return element.get(f'{{{TTS_NAMESPACE}}}color', color)


def _srt_color(color):
    if not color:
        return None
    if re.fullmatch(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?', color):
        return color[:7]
    if re.fullmatch(r'[A-Za-z]+', color):
        return color
    return None


def _render_element(element, inherited_color, styles, cache):
    if _local_name(element.tag) == 'br':
        return '\n'

    color = _element_color(element, inherited_color, styles, cache)
    rendered = []
    if element.text and not (element.text.isspace() and '\n' in element.text):
        rendered.append(html.escape(element.text, quote=False))

    for child in element:
        rendered.append(_render_element(child, color, styles, cache))
        if child.tail and not (child.tail.isspace() and '\n' in child.tail):
            rendered.append(html.escape(child.tail, quote=False))

    content = ''.join(rendered)
    srt_color = _srt_color(color)
    if srt_color and srt_color != _srt_color(inherited_color):
        return f'<font color="{srt_color}">{content}</font>'
    return content


def _parse_clock_time(value):
    match = re.fullmatch(r'(\d{2,}):(\d{2}):(\d{2})(?:\.(\d+))?', value or '')
    if not match:
        raise ValueError(f'Nicht unterstuetztes TTML-Zeitformat: {value!r}')

    hours, minutes, seconds = (int(part) for part in match.group(1, 2, 3))
    if minutes > 59 or seconds > 59:
        raise ValueError(f'Ungueltiger TTML-Zeitcode: {value!r}')
    fraction = match.group(4) or '0'
    milliseconds = int((Decimal(f'0.{fraction}') * 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    total_milliseconds = ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds
    return total_milliseconds


def _format_srt_time(total_milliseconds):
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'


def convert_ttml_to_srt(xml_content):
    """Convert TTML with clock-time cues into SRT, retaining text colors as font tags."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as error:
        raise ValueError(f'Ungueltiges XML/TTML: {error}') from error
    if _local_name(root.tag) != 'tt':
        raise ValueError('Die XML-Datei ist kein TTML-Untertiteldokument.')

    body = next((element for element in root.iter() if _local_name(element.tag) == 'body'), None)
    if body is None:
        raise ValueError('Das TTML-Dokument enthaelt keinen Untertitel-Body.')

    styles = {
        _style_id(element): element
        for element in root.iter()
        if _local_name(element.tag) == 'style' and _style_id(element)
    }
    style_cache = {}
    paragraphs = [element for element in body.iter() if _local_name(element.tag) == 'p']
    if not paragraphs:
        raise ValueError('Das TTML-Dokument enthaelt keine Untertitel-Cues.')

    cues = []
    for paragraph in paragraphs:
        start = _parse_clock_time(paragraph.get('begin'))
        end = _parse_clock_time(paragraph.get('end'))
        if end <= start:
            raise ValueError('Ein TTML-Cue hat eine ungueltige Endzeit.')
        text = _render_element(paragraph, None, styles, style_cache).strip()
        if not text:
            continue
        cues.append(
            f'{len(cues) + 1}\n{_format_srt_time(start)} --> {_format_srt_time(end)}\n{text}'
        )

    if not cues:
        raise ValueError('Das TTML-Dokument enthaelt keine lesbaren Untertitel-Cues.')
    return '\n\n'.join(cues) + '\n'
