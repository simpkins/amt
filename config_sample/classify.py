#!/usr/bin/python3 -tt
#
# Example mail tagging logic.
#
# Copyright (c) 2015, Adam Simpkins
#
import re


FB_GROUP_RE = re.compile('([^>]+)\.groups\.facebook\.com$')

# Settings for classifying messages from Phabricator.
# My Phabricator user PHID.
MY_PHID = '<PHID-USER-00000000000000000000>'
HERALD_RULE_RE = re.compile(r'\s*<(\d+)>,?\s*')
# Tags to add based on Phabricator herald rules that were matched
HERALD_RULES = {
    12345: ['diff-project1'],
    45678: ['diff-project2'],
}

FB_GROUP_NAMES = {
    # For Facebook groups that don't have vanity names assigned,
    # you can add your own mappings here to translate the numerical group ID to
    # a nicer to read string.
    '123456789012345': 'example-group',
}

# Tags to assign if an address is present in the To or Cc headers
RECIPIENT_TO_TAGS = {
    'engineers@example.com': ['eng'],
    'noc@example.com': ['noc'],
}

# Tags to assign based on lists present in a List-Id header.
LIST_ID_TO_TAGS = {
    'dev.example.org': ['dev'],
}


class MessageClassifier:
    def __init__(self, msg):
        self.msg = msg
        self.tags = set()

    def classify(self):
        self.get_destination_tags()
        self.get_source_tags()

        self.add_meta_tags()
        self.add_hipri_tag()
        return self.tags

    def add_tag(self, tag):
        self.tags.add(tag)

    def add_tags(self, tags):
        self.tags.update(tags)

    def get_destination_tags(self):
        '''
        Add tags based on the destination address.
        '''
        list_ids = self.msg.get_addresses('List-Id')
        if list_ids is None:
            list_ids = ()
        for list_id in list_ids:
            list_id = list_id.addr_spec
            m = FB_GROUP_RE.match(list_id)
            if m:
                self.add_tag('facebook')
                group_id = m.group(1)
                group_name = FB_GROUP_NAMES.get(group_id, group_id)
                self.add_tag('fbg-' + group_name)
                continue

            if list_id in LIST_ID_TO_TAGS:
                self.add_tags(LIST_ID_TO_TAGS[list_id])
                continue

        # Add other tags based on the recipients
        for addr in self.msg.to:
            self.add_tags_from_recipient(addr)
        for addr in self.msg.cc:
            self.add_tags_from_recipient(addr)

    def add_tags_from_recipient(self, addr):
        tags = RECIPIENT_TO_TAGS.get(addr.addr_spec)
        if tags:
            self.add_tags(tags)

    def get_herald_rules(self):
        rules = self.msg.get('X-Herald-Rules')
        if not rules:
            return set()

        rule_ids = set()
        parts = rules.split()
        for part in parts:
            m = HERALD_RULE_RE.match(part)
            if not m:
                continue
            rule_ids.add(int(m.group(1)))

        return rule_ids

    def get_source_tags(self):
        """
        Add tags based on the message source.

        This function contains all classifiers that add tags based on the
        message source.  Since there is generally only one message source,
        these classifiers are all mutually exclusive, and this function can
        return early as soon as one classifier matches.
        """
        if self.msg.get('X-Phabricator-Sent-This-Message'):
            self.add_tag('phabricator')
            if '[Differential]' in self.msg.subject:
                self.add_tag('diff')

                # Add tags based on herald rules
                rules = self.get_herald_rules()
                for hr, tags in HERALD_RULES.items():
                    if hr in rules:
                        self.add_tags(tags)

                # Add tags if I am the author or a reviewer
                if self.msg.get('X-Differential-Author') == MY_PHID:
                    self.add_tag('diff-author')
                else:
                    reviewers = self.msg.get_all('X-Differential-Reviewer', ())
                    if MY_PHID in reviewers:
                        self.add_tag('diff-reviewer')

                return
            if '[Commit]' in self.msg.subject:
                self.add_tag('commit')
                return
            return

        # Bug reports
        if '[bug]' in self.msg.subject:
            self.add_tag('bug')
            # Add extra processing of bug message headers here if you wanted...

        if not self.msg.from_addr:
            return

        # Add tags based on self.msg.from_addr here...

    def add_meta_tags(self):
        '''
        Add tags based on other tags already applied to the message.
        '''
        work_tags = ('eng', 'noc', 'bugs')
        self.add_meta_tag('work', ti_tags)

    def add_meta_tag(self, meta_tag, tags):
        for tag in tags:
            if tag in self.tags:
                self.add_tag(meta_tag)
                return

    def add_hipri_tag(self):
        '''
        Add the tag 'hipri' to high-priority messages.
        '''
        # Don't add hipri to messages that we explicitly know aren't
        # high-priority.
        if 'facebook' in self.tags:
            return
        if 'buildbot' in self.tags:
            return
        if 'phabricator' in self.tags:
            return
        if 'bug' in self.tags and not 'my-bug' in self.tags:
            return
        if 'office-status' in self.tags:
            return

        # Conservatively assume a message is high priority if it didn't match
        # one of our non-hi-pri filters.
        self.add_tag('hipri')


def classify_msg(msg):
    return MessageClassifier(msg).classify()
