#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import datetime
import email.header
import email.parser
import email.utils

import imap_util


class Message:
    '''
    Represents an email message.

    Independent of the underlying mailbox type.
    Uses email.message.Message internally, but provides a more user-friendly
    interface.  Also keeps track of the receipt timestamp, and any message
    flags that associated with it.
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
        elif isinstance(timestamp, (int, long)):
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
        self.to = AddressList()
        self.cc = AddressList()
        self.from_addr = AddressList()
        self.subject = None
        for k, v in self.msg._headers:
            if k.lower() == 'to':
                self.to.extend(self._parse_addresses(v))
            elif k.lower() == 'cc':
                self.cc.extend(self._parse_addresses(v))
            elif k.lower() == 'from':
                self.from_addr.extend(self._parse_addresses(v))
            elif self.subject is None and k.lower() == 'subject':
                self.subject = self._decode_header(k, v)

        # The body will be parsed lazily if needed
        self._body_text = None

    @classmethod
    def from_imap(cls, fetch_response):
        '''
        Create a new Message from an IMAP FETCH response that includes at
        least BODY[], INTERNALDATE, and FLAGS fields.
        '''
        body = fetch_response['BODY[]']
        timestamp = fetch_response['INTERNALDATE']
        imap_flags = fetch_response['FLAGS']

        parser = email.parser.BytesParser()
        msg = parser.parsebytes(body)

        flags = set()
        custom_flags = set()
        for flag in imap_flags:
            if flag == imap_util.FLAG_SEEN:
                flags.add(cls.FLAG_SEEN)
            elif flag == imap_util.FLAG_ANSWERED:
                flags.add(cls.FLAG_REPLIED_TO)
            elif flag == imap_util.FLAG_FLAGGED:
                flags.add(cls.FLAG_FLAGGED)
            elif flag == imap_util.FLAG_DELETED:
                flags.add(cls.FLAG_DELETED)
            elif flag == imap_util.FLAG_DRAFT:
                flags.add(cls.FLAG_DRAFT)
            else:
                custom_flags.add(flag)

        return cls(msg, timestamp, flags, custom_flags)

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
        for k, v in self._headers:
            if k.lower() == name:
                return self._decode_header(k, v)
        return default

    def get_header_all(self, name, default=None):
        '''
        Return a list of all headers with the specified name.

        Returns a list of email.header.Header objects, or the specified default
        if no header exists with this name.
        '''
        results = []
        name = name.lower()
        for k, v in self._headers:
            if k.lower() == name:
                results.append(self._decode_header(k, v))

        if not results:
            return default
        return results

    def _decode_header(self, name, value, errors='replace'):
        if hasattr(name, '_chunks'):
            # Looks like it is already an email.header.Header object
            return value

        hdr = email.header.Header(header_name=name)
        parts = email.header.decode_header(value)
        for part, charset in parts:
            hdr.append(part, charset, errors=errors)
        return hdr

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
