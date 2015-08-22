#!/usr/bin/python3 -tt
#
# Sample config file for amt_urlview.
#
# This allows you to implement custom logic for guessing the best URL to go to
# when "amt_urlview -g" is invoked.
#
# Copyright (c) 2015, Adam Simpkins
#
import re

import amt.message
import amt.urlview

MSG_DIFFERENTIAL = 'differential'
MSG_FB_NOTIFICATION = 'fb-notification'
MSG_UNKNOWN = 'unknown'

FB_GROUP_RE = re.compile('([^>]+)\.groups\.facebook\.com$')


def guess_best_url(msg):
    '''
    guess_best_url() will be called to guess the best URL to go to
    for a given message.
    '''
    msg_type = get_msg_type(msg)
    if msg_type == MSG_FB_NOTIFICATION:
        return guess_best_url_fb_post(msg)
    elif msg_type == MSG_DIFFERENTIAL:
        return guess_best_url_diff(msg)

    # You can add processing for other message types here...
    # e.g., bugzilla tasks, other task tools, mailing list archive posts, etc.

    return None


def get_msg_type(msg):
    if msg.get('X-Facebook-Notify'):
        return MSG_FB_NOTIFICATION

    subject = msg.subject
    if subject.find('[Differential]') >= 0:
        return MSG_DIFFERENTIAL

    # Unfortunately I've seen some recent FB notifications without an
    # X-Facebook-Notify header.  Not sure if this is a bug or not.
    list_ids = msg.get_addresses('List-Id')
    if list_ids is None:
        list_ids = ()
    for list_id in list_ids:
        if FB_GROUP_RE.match(list_id.addr_spec) is not None:
            return MSG_FB_NOTIFICATION

    return MSG_UNKNOWN


def guess_best_url_fb_post(msg):
    '''
    For facebook notification emails, go to the link to view
    the post on facebook.
    '''
    urls = amt.urlview.extract_urls_generic(msg)
    # The bottom of the page has a link to the post.
    # Find the last URL that matches the expected href label.
    best_url = None
    for url in urls:
        if (url.label == 'View Post on Facebook' or
            url.label == 'View Post'):
            best_url = url
    return best_url


def guess_best_url_diff(msg):
    # For differential mails, go to the revision page
    urls = extract_urls_diff(msg)
    for url in urls:
        if url.label == 'REVISION DETAIL':
            return url
    return None


def extract_urls_diff(msg):
    '''
    Extract URLs from a Phabricator differential message.
    '''
    # Differential emails currently have only text payloads
    # Get the text payload
    preferred_types = ['text/plain', 'text/html']
    body_msgs = list(msg.iter_body_msgs(preferred_types))
    if len(body_msgs) != 1:
        return amt.urlview.extract_urls_generic()

    payload = amt.message.decode_payload(body_msgs[0])
    lines = payload.splitlines()

    all_urls = []
    def add_urls_from_section(label, urls):
        if len(urls) == 1:
            urls[0].label = label
            all_urls.append(urls[0])
        else:
            for n, url in enumerate(urls):
                if label is not None:
                    url.label = '%s %d' % (label, n)
                all_urls.append(url)

    cur_label = None
    cur_urls = []
    for line in lines:
        if not line.startswith(' ') and line.isupper():
            add_urls_from_section(cur_label, cur_urls)
            cur_label = line
            cur_urls = []
        else:
            cur_urls.extend(amt.urlview.get_urls_text(line))
    add_urls_from_section(cur_label, cur_urls)

    return all_urls
