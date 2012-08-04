#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import base64
import datetime
import email.header
import email.message
import email.parser
import email.utils
import hashlib
import os
import re
import time


class Message:
    '''
    Represents an email message.

    Independent of the underlying mailbox type.
    Uses email.message.Message internally, but provides a more user-friendly
    interface.  Also keeps track of the receipt timestamp, and any flags
    associated with the message.
    '''
    FLAG_NEW = 'N'
    FLAG_SEEN = 'S'
    FLAG_FORWARDED = 'F'
    FLAG_REPLIED_TO = 'R'
    FLAG_FLAGGED = '!'
    FLAG_DELETED = 'T'  # Trash
    FLAG_DRAFT = 'D'

    def __init__(self, msg, timestamp, flags, custom_flags):
        # An email.message.Message object
        self.msg = msg

        if isinstance(timestamp, datetime.datetime):
            self.datetime = timestamp
            self.timestamp = timestamp.timestamp()
        elif isinstance(timestamp, (int, float)):
            self.timestamp = timestamp
            self.datetime = datetime.datetime.fromtimestamp(timestamp)
        else:
            raise TypeError('expected timestamp to be a datetime object '
                            'or a Unix timestamp')

        # A set of Message.FLAG_* values
        self.flags = flags
        # A set of other arbitrary string flags
        self.custom_flags = custom_flags

        # Parse commonly used fields
        # These should be accessed with the @property methods below,
        # since we currently don't support updating self.msg when they are
        # changed.
        self._to = AddressList()
        self._cc = AddressList()
        self._from_addr = AddressList()
        self._subject_hdr = None
        self._subject = None
        for k, v in self.msg._headers:
            if k.lower() == 'to':
                self._to.extend(self._parse_addresses(v))
            elif k.lower() == 'cc':
                self._cc.extend(self._parse_addresses(v))
            elif k.lower() == 'from':
                self._from_addr.extend(self._parse_addresses(v))
            elif self._subject is None and k.lower() == 'subject':
                self._subject_hdr = self._decode_header(k, v)
                self._subject = str(self._subject_hdr)

        # The body will be parsed lazily if needed
        self._body_text = None

    @property
    def to(self):
        return self._to

    @property
    def cc(self):
        return self._cc

    @property
    def from_addr(self):
        return self._from_addr

    @property
    def subject(self):
        return self._subject or ''

    @classmethod
    def from_maildir(cls, path):
        # Parse the message itself
        parser = email.parser.BytesParser()
        with open(path, 'rb') as f:
            s = os.fstat(f.fileno())
            timestamp = s.st_mtime
            msg = parser.parse(f)

        # Load the metadata from the file name
        parent, basename = os.path.split(path)
        parts = basename.split(':', 1)
        if len(parts) > 1:
            info = parts[1]
        else:
            info = ''

        flags = set()
        if info.startswith('2,'):
            if 'P' in info:
                flags.add(cls.FLAG_FORWARDED)
            if 'R' in info:
                flags.add(cls.FLAG_REPLIED_TO)
            if 'S' in info:
                flags.add(cls.FLAG_SEEN)
            if 'T' in info:
                flags.add(cls.FLAG_DELETED)
            if 'D' in info:
                flags.add(cls.FLAG_DRAFT)
            if 'F' in info:
                flags.add(cls.FLAG_FLAGGED)

        subdir = os.path.basename(parent)
        if subdir == 'new':
            flags.add(cls.FLAG_NEW)

        custom_flags = set()
        return cls(msg, timestamp, flags, custom_flags)

    @classmethod
    def from_bytes(cls, data, timestamp=None, flags=None, custom_flags=None):
        if timestamp is None:
            timestamp = time.time()
        if flags is None:
            flags = set()
        else:
            assert isinstance(flags, set)
        if custom_flags is None:
            custom_flags = set()
        else:
            assert isinstance(flags, set)

        parser = email.parser.BytesParser()
        msg = parser.parsebytes(data)
        return cls(msg, timestamp, flags, custom_flags)

    def compute_maildir_info(self):
        '''
        Compute the maildir info string to be appended to the end of a maildir
        file name.
        '''
        parts = ['2,']

        # Note: The flags must appear in ASCII order
        if self.FLAG_DRAFT in self.flags:
            parts.append('D')
        if self.FLAG_FLAGGED in self.flags:
            parts.append('F')
        if self.FLAG_FORWARDED in self.flags:
            parts.append('P')
        if self.FLAG_REPLIED_TO in self.flags:
            parts.append('R')
        if self.FLAG_SEEN in self.flags:
            parts.append('S')
        if self.FLAG_DELETED in self.flags:
            parts.append('T')

        return ''.join(parts)

    @property
    def body_text(self):
        if self._body_text is None:
            self._body_text = self._compute_body_text()
        return self._body_text

    def get_header(self, name, default=None):
        '''
        Get the value of a specified header.

        If the header appears multiple times in the message, only the first
        instance is returned.

        Returns an email.header.Header, or the specified default if no header
        exists with this name.
        '''
        name = name.lower()
        for k, v in self.msg._headers:
            if k.lower() == name:
                return self._decode_header(k, v)
        return default

    def get(self, name, default=None):
        '''
        Get the value of a specified header.

        If the header appears multiple times in the message, only the first
        instance is returned.

        Returns a string, or the specified default if no header exists with
        this name.
        '''
        hdr = self.get_header(name)
        if hdr is None:
            return default
        return str(hdr)

    def get_header_all(self, name, default=None):
        '''
        Return a list of all headers with the specified name.

        Returns a list of email.header.Header objects, or the specified default
        if no header exists with this name.
        '''
        results = []
        name = name.lower()
        for k, v in self.msg._headers:
            if k.lower() == name:
                results.append(self._decode_header(k, v))

        if not results:
            return default
        return results

    def get_all(self, name, default=None):
        '''
        Return a list of all headers with the specified name.

        Returns a list of strings, or the specified default if no header exists
        with this name.
        '''
        hdrs = self.get_header_all(name, None)
        if hdrs is None:
            return default
        return [str(hdr) for hdr in hdrs]

    def get_addresses(self, header):
        '''
        Get all instances of the specified header, parse them as addresses, and
        return them as an AddressList.
        '''
        values = self.get_all(header, [])
        addresses = email.utils.getaddresses(values)
        return AddressList(addresses)

    def remove_header(self, name):
        '''
        Delete all occurences of a header.

        Does nothing if the header was not present.
        '''
        del self.msg[name]

    def add_header(self, name, value):
        self.msg[name] = self._decode_header(name, value)

    def _decode_header(self, name, value, errors='replace'):
        # TODO: Newer versions of python support a 'policy' argument to the
        # email.message.Message constructor, which we could use instead of
        # having to manually invoke _decode_header() in our own wrapper
        # functions.

        if hasattr(value, '_chunks'):
            # Looks like it is already an email.header.Header object
            return value

        hdr = email.header.Header(header_name=name)
        parts = email.header.decode_header(value)
        for part, charset in parts:
            hdr.append(part, charset, errors=errors)
        return hdr

    def get_message_id(self):
        '''
        Returns the contents of the Message-ID header, if it looks like a valid
        Message-ID.  If no Message-ID header is present, or if it is invalid,
        None is returned.
        '''
        message_id = self.get('Message-ID')
        if message_id is None:
            return None

        message_id = message_id.strip()
        if _is_valid_message_id(message_id):
            return message_id
        return None

    def get_referenced_ids(self):
        '''
        Get the set of Message-IDs contained in the References and In-Reply-To
        header.

        This parses the References and In-Reply-To headers, and only returns
        the valid Message-IDs that are found.  The returned list will not
        contain duplicates (if the same Message-ID is present in both the
        References and In-Reply-To header, for example).
        '''
        results = []

        # For some useful info about the References and In-Reply-To headers
        # in practice, see http://www.jwz.org/doc/threading.html
        for references in self.get_all('References', []):
            parts = references.split()
            for part in parts:
                if _is_valid_message_id(part):
                    results.append(part)

        global _message_id_regex
        for header in self.get_all('In-Reply-To', []):
            # Search for something that looks like <ID@HOST>
            m = _message_id_regex.search(header)
            if not m:
                continue
            results.append(m.group(1))

        return results

    def get_subject_stem(self):
        '''
        Get the subject, with any "Re:", "Fwd:", and similar prefixes stripped
        off.
        '''
        subj = self.subject.strip()

        prefixes = ['re:', 'fwd:', 'fw:']
        while True:
            for prefix in prefixes:
                if subj.lower().startswith(prefix):
                    subj = subj[len(prefix):].lstrip()
                    break
            else:
                return subj

    def binary_fingerprint(self):
        h = hashlib.md5()

        # Hash the Subject, From, and Message-ID headers
        for header in (self._subject_hdr, self.get_header('From'),
                       self.get_header('Message-ID')):
            if header is None:
                continue
            encoded = header.encode()[:40].encode('ascii', 'surrogateescape')
            h.update(encoded)

        # Hash the first 40 bytes of the first body part
        for part in self.iter_body_msgs():
            payload = part.get_payload(decode=False)
            if isinstance(payload, str):
                payload = payload.encode('ascii', 'surrogateescape')
            h.update(payload[:40])
            break

        return h.digest()

    def fingerprint(self):
        return base64.b64encode(self.binary_fingerprint())

    def _parse_addresses(self, header):
        return email.utils.getaddresses([header])

    def _compute_body_text(self):
        return '\n'.join(decode_payload(msg) for msg in self.iter_body_msgs())

    def iter_body_msgs(self, preferred_types=None):
        '''
        Return an iterator over the sub-messages that make up the message body.

        This looks through all of the sub-messages, and returns a flat list of
        only the leaf messages.  For multipart/alternative parts, exactly one
        sub-message will be selected from the alternatives, based on the
        ordering in the preferred_types argument.

        If preferred_types is None, it defaults to ['text/plain', 'text/html']
        '''
        if preferred_types is None:
            preferred_types = ('text/plain', 'text/html')
        return TextBodyIterator(self.msg, preferred_types)


class BasicBodyIterator:
    '''
    An iterator that iterates over all messages and their submessages.

    This iterates in depth-first order, with multipart messages returned before
    their children.
    '''
    def __init__(self, msg):
        self.stack = [msg]

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            if not self.stack:
                raise StopIteration()

            msg = self.stack.pop()
            self.add_children(msg)

            if self.should_return_msg(msg):
                return msg

    def should_return_msg(self, msg):
        return True

    def add_children(self, msg):
        if not msg.is_multipart():
            return

        # Append all subparts, in reversed order so they will be
        # ordered correctly when we pop them off from back to front.
        self.stack.extend(reversed(msg.get_payload()))


class BodyIterator(BasicBodyIterator):
    '''
    A BodyIterator that handles multipart/alternative messages specially, and
    only returns the most preferred message type.
    '''
    def __init__(self, msg, preferred_mime_types):
        super().__init__(msg)
        self.selector = MultipartAlternativeSelector(preferred_mime_types)

    def add_children(self, msg):
        if not msg.is_multipart():
            return

        if msg.get_content_type() == 'multipart/alternative':
            child = self.selector.choose(msg)
            self.stack.append(child)
        else:
            # Append all subparts, in reversed order so they will be
            # ordered correctly when we pop them off from back to front.
            self.stack.extend(reversed(msg.get_payload()))


class TextBodyIterator(BodyIterator):
    '''
    A BodyIterator that only returns the text
    '''
    def should_return_msg(self, msg):
        if msg.is_multipart():
            return False
        return msg.get_content_maintype() == 'text'


class MultipartAlternativeSelector:
    def __init__(self, preferred_mime_types):
        # Accept preferred_mime_types as an ordered list/tuple,
        # but convert it into a dictionary mapping mime-type --> preference,
        # with higher preferences being better
        self.preferred_types = {}
        for idx, content_type in enumerate(preferred_mime_types):
            pref = len(preferred_mime_types) - idx
            self.preferred_types.setdefault(content_type, pref)

    def choose(self, msg):
        assert msg.get_content_type() == 'multipart/alternative'

        best_pref = None
        best = None
        multiparts = []

        for child in msg.get_payload():
            content_type = child.get_content_type()

            pref = self.preferred_types.get(content_type, -1)
            if best_pref is None or pref > best_pref:
                best_pref = pref
                best = child

            if child.is_multipart():
                multiparts.append(child)

        if best_pref >= 0:
            # We found one of the preferred content types
            return best

        # We didn't find one of the preferred types.  If there were multipart
        # submessages, pick one of them, since they may still have a
        # sub-message with the desired type.
        #
        # TODO: We could do a better job of finding one of the multipart
        # messages that actually does have a submessage of the desired type.
        if multiparts:
            return multiparts[0]

        # Just return the first sub-message
        return best


class AddressList(list):
    def contains(self, value):
        for name, addr in self:
            if value in name:
                return True
            if value in addr:
                return True
        return False

    def icontains(self, value):
        l = value.lower()
        for name, addr in self:
            if l in name.lower():
                return True
            if l in addr.lower():
                return True
        return False


def decode_payload(msg, errors='replace'):
    assert msg.is_multipart() == False
    payload = msg.get_payload(decode=True)

    # Look for the character set in the content-type header parameters.
    # Note that msg.get_charset() doesn't do this; it only returns a value if
    # you have previously set it with msg.set_charset()
    charset = 'latin-1'  # default if no other value found
    for key, value in msg.get_params([]):
        if key == 'charset':
            charset = value
            # Keep looking; use the last charset parameter we find

    return payload.decode(charset, errors=errors)


def _format_address(value):
    if not isinstance(value, (list, tuple)):
        raise TypeError('argument must be a (name, address) tuple, '
                        'or a list of such tuples, not %s' %
                        type(value).__name__)

    # Accept a single (name, value) pair, and turn it into a list
    if isinstance(value[0], str):
        value = [value]

    formatted = []
    for name, addr in value:
        result = email.utils.formataddr((name, addr))
        formatted.append(result)
    return ' '.join(formatted)


_message_id_regex = re.compile('(<[^ @>]+@[^ @>]+>)')

def _is_valid_message_id(value):
    # We could verify that the ID contents are actually RFC2822 compliant,
    # but we don't bother for now.
    return (value.startswith('<') and value.endswith('>'))


def new_message(subject, body, from_addr, to, cc=None,
                message_id=None, timestamp=None):
    msg = email.message.Message()
    msg['Subject'] = subject
    msg['From'] = _format_address(from_addr)
    msg['To'] = _format_address(to)
    if cc is not None:
        msg['Cc'] = _format_address(cc)
    msg.set_payload(body, 'utf-8')

    if message_id is None:
        message_id = email.utils.make_msgid()
    msg['Message-ID'] = message_id

    if timestamp is None:
        timestamp = time.time()
    return Message(msg, timestamp, flags=[], custom_flags=[])
