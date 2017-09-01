#!/usr/bin/python3 -tt
#
# Copyright (c) 2013, Adam Simpkins
#
import bs4
import re
import os
import subprocess
import sys
import urllib.parse

from . import message
from .term import Terminal

URL_PATTERN = ('(?:http|https|ftp)://[^ <>"\t\n\r\f]*|'
               '[-a-zA-Z0-9._]+\.(?:com|net|org|gov)(?:/[^ <>"\t\n\r\f]*|\\b)')
URL_RE = re.compile(URL_PATTERN)


class URL:
    def __init__(self, url, label=None):
        self.raw_url = url
        self.url_obj = urllib.parse.urlparse(self.raw_url)
        self.label = label

        demangled_url = self.demangle(self.url_obj)
        if isinstance(demangled_url, str):
            self._display_url = demangled_url
        else:
            self._display_url = urllib.parse.urlunparse(demangled_url)

    def __str__(self):
        return self.raw_url

    @property
    def display_url(self):
        '''
        A string to use to display the URL to the user.

        This value may have been modified to make it more user-friendly.
        For example, converting Facebook linkshim URLs to the destination URL
        without the facebook.com prefix.
        '''
        return self._display_url

    @property
    def effective_url(self):
        '''
        Get the URL string to use for going to the URL with a browser.
        '''
        # For now we always use the original raw URL.
        #
        # We could potentially use the de-link-shimmed version, but doing so
        # doesn't seem to provide much benefit.  This will allow FB to prevent
        # the redirect if the URL has been deemed malicious.  This also ensures
        # that the URL will always work even if we didn't perform the
        # de-link-shimming the same way that FB would.
        return self.raw_url

    def demangle(self, url_obj):
        if url_obj.netloc == 'www.facebook.com':
            # Strip Facebook notification link shims
            if url_obj.path == '/n/':
                return self.demangle_fb_notification_shim(url_obj)
            elif url_obj.path.startswith('/l/'):
                return self.demangle_fb_link_shim(url_obj)
        elif url_obj.netloc == 'urldefense.proofpoint.com':
            # Decode proofpoint URL defense URLS.
            return self.demangle_proofpoint_urldefense(url_obj)
        return url_obj

    def demangle_fb_notification_shim(self, url_obj):
        qparams = urllib.parse.parse_qsl(url_obj.query,
                                         keep_blank_values=True)
        if not qparams:
            # invalid, or old style link shim
            # Just use the raw URL.
            return url_obj
        (next_path, empty) = qparams[0]
        if empty != '':
            # invalid, or old style link shim
            # Just use the raw URL.
            return url_obj
        if not next_path.startswith('/'):
            next_path = '/' + next_path

        next_params = urllib.parse.parse_qs(url_obj.query)
        next_fragment = next_params.get('fragment', '')

        # Strip parameters that aren't passed on to the next URL
        for param in ['bcode', 'lloc', 'mid', 'd', 'n_m', 'aref', 'fragment']:
            if param in next_params:
                del next_params[param]

        next_query = urllib.parse.urlencode(next_params)
        next_url = urllib.parse.ParseResult(url_obj.scheme, url_obj.netloc,
                                            next_path, url_obj.params,
                                            next_query, next_fragment)

        # Recursively demangle the next URL.
        # Notification URLs are frequently links to the www.facebook.com/l/
        # linkshim endpoint.
        return self.demangle(next_url)

    def demangle_fb_link_shim(self, url_obj):
        r = re.compile('^/l/([a-zA-Z0-9\_\-\.]*)(?:;|/)(?P<url>.*)')
        m = r.match(url_obj.path)
        if not m:
            return url_obj

        parts = m.group('url').split('/', 1)
        next_netloc = parts[0]
        if len(parts) == 1:
            next_path = ''
        else:
            next_path = parts[1]

        next_url = urllib.parse.ParseResult('http', next_netloc, next_path,
                                            '', url_obj.query,
                                            url_obj.fragment)
        return next_url

    def demangle_proofpoint_urldefense(self, url_obj):
        query = urllib.parse.parse_qs(url_obj.query)
        u_param = query.get('u')
        if not u_param:
            return url_obj

        translated = u_param[0].translate(str.maketrans("-_", '%/'))
        next_url_str = urllib.parse.unquote(translated)
        return urllib.parse.urlparse(next_url_str)


def get_urls(msg):
    payload = message.decode_payload(msg)
    if msg.get_content_type() == 'text/html':
        return get_urls_html(payload)
    return get_urls_text(payload)


def _html_text_contents(elem, results):
    if isinstance(elem, str):
        results.append(elem)
        return

    for child in elem.contents:
        _html_text_contents(child, results)


def get_urls_html(payload):
    soup = bs4.BeautifulSoup(payload, 'lxml')

    urls = []
    for tag in soup.find_all('a'):
        url_text = tag.get('href')
        if url_text is None:
            continue

        # Join all of the text underneath this anchor to construct the label.
        results = []
        for elem in tag.contents:
            _html_text_contents(elem, results)
        if not results:
            value = None
        else:
            value = ' '.join(results)
            # Truncate to 60 characters just for legibility
            value = value[:60]
            # Replace all non-breaking space characters with spaces.
            value = value.replace('\N{NO-BREAK SPACE}', ' ')

        urls.append(URL(url_text, value))

    return urls


def get_urls_text(payload):
    matches = URL_RE.findall(payload)
    return [URL(url_text) for url_text in matches]


def extract_urls_generic(msg):
    # Prefer text/html over text/plain when selecting from
    # multipart/alternative messages.
    preferred_types = ['text/html', 'text/plain']

    urls = []
    for msg in msg.iter_body_msgs(preferred_types):
        urls.extend(get_urls(msg))

    return urls


def print_urls(urls):
    num_field_width = len('%d: ' % len(urls))

    for n, url in enumerate(urls):
        if url.label:
            print('%*d: %s' % (num_field_width, n, url.label))
            print('%s  %s' % (' ' * num_field_width, url.display_url))
        else:
            print('%*d: %s' % (num_field_width, n, url.display_url))


def extract_urls(amt_config, msg):
    if hasattr(amt_config.urlview, 'extract_urls'):
        return amt_config.urlview.extract_urls(msg)
    else:
        return extract_urls_generic(msg)


def view_url(url):
    cmd = ['x-www-browser', url.effective_url]
    subprocess.check_call(cmd)


def guess_best_url(amt_config, msg):
    if hasattr(amt_config.urlview, 'guess_best_url'):
        best_url = amt_config.urlview.guess_best_url(msg)
    else:
        best_url = None

    # If don't have any special logic to guess the best URL,
    # extract all of the URLs.  If there is only 1 URL, use it as the best.
    # Otherwise just fall back to the normal selection interface.
    if best_url is None:
        urls = extract_urls(amt_config, msg)
        if len(urls) == 1:
            best_url = urls[0]
        else:
            select_urls(amt_config, urls)
            return

    view_url(best_url)


def select_urls_term(urls, root):
    if not urls:
        root.writeln(-1, 'No URLs found.  Press any key to exit.')
        root.term.flush()
        root.term.getch()
        return

    def redraw():
        root.writeln(0, 'URL List:')

        # TODO: Handle scrolling for long URLS and too many URLs to fit on one
        # screen
        idx_width = len('%d' % len(urls))
        line_num = 1
        fmt = '{idx:{idx_width}}{idx_sep} {contents}'
        for n, url in enumerate(urls):
            if url.label:
                line = fmt.format(idx=n, idx_width=idx_width, idx_sep=':',
                                  contents=url.label)
                root.writeln(line_num, '{0}', line)
                line = fmt.format(idx='', idx_width=idx_width, idx_sep=' ',
                                  contents=url.display_url)
                root.writeln(line_num + 1, '{0}', line)
                line_num += 2
            else:
                line = fmt.format(idx=n, idx_width=idx_width, idx_sep=':',
                                  contents=url.display_url)
                root.writeln(line_num, '{0}', line)
                line_num += 1

            if line_num + 2 >= root.height:
                break

    status = None
    while True:
        redraw()
        if status is not None:
            root.writeln(-2, '{0}', status)
        root.term.flush()

        with root.term.shell_mode():
            line = input('Enter a URL Number: ')

        if line == 'q':
            return None

        try:
            num = int(line)
        except ValueError:
            status = 'Invalid number %r' % line
            continue

        if num < 0:
            status = 'Invalid index %r: may not be negative' % num
            continue
        if num >= len(urls):
            status = 'Index too large: %r' % num
            continue

        return urls[num]


def select_urls(amt_config, urls):
    if sys.stdout.isatty():
        # stdin may have been used to pipe data to us.
        # Reset stdin to be our controlling terminal
        os.dup2(sys.stdout.fileno(), sys.stdin.fileno())
        term = Terminal()
        with term.program_mode() as root:
            try:
                url = select_urls_term(urls, root)
            except KeyboardInterrupt:
                url = None
        if url is not None:
            view_url(url)
    else:
        print_urls(urls)
