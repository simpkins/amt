#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from . import color


class TagDictionary:
    def __init__(self):
        self._tags = {}
        self._tag_prefixes = {}
        self._meta_tags = []

        self._color_priorities = []

    @property
    def meta_tags(self):
        return self._meta_tags

    def new_tag(self, name, description, **kwargs):
        tag = Tag(name, description, **kwargs)
        self._insert_tag(tag)
        return tag

    def new_tag_prefix(self, prefix, description, **kwargs):
        tag_prefix = TagPrefix(prefix, description, **kwargs)

        for other in self._tag_prefixes.values():
            if (other.prefix.startswith(prefix) or
                prefix.startswith(other.prefix)):
                raise Exception('tag prefix "%s" collides with existing '
                                'prefix "%s"' % (prefix, other.prefix))

        self._tag_prefixes[prefix] = tag_prefix
        return tag_prefix

    def new_meta_tag(self, name, description, **kwargs):
        tag = MetaTag(name, description, **kwargs)
        self._insert_tag(tag)
        self._meta_tags.append(tag)
        return tag

    def get_tag(self, name, suffix=None):
        '''
        Get a tag with the specified name.

        If no Tag with this name has already been defined, a new Tag will be
        created and returned.
        '''
        if suffix is not None:
            # Check to see if we already have a tag with this name first
            full_name = name + suffix
        else:
            full_name = name

        # Check to see if we already have a tag with this name
        existing_tag = self._tags.get(full_name)
        if existing_tag is not None:
            return existing_tag

        # If this is a request for a prefix tag, create the tag with
        # the information from the TagPrefix
        if suffix is not None:
            tag_prefix = self._tag_prefixes.get(name)
            if tag_prefix is None:
                raise KeyError('no tag prefix "%s"' % (name,))

            tag = tag_prefix.create_tag(suffix)
        else:
            tag = Tag(name, 'dynamically created')

        self._insert_tag(tag)
        return tag

    def _insert_tag(self, tag):
        # Add tags to _color_priorities in the order they are defined
        # If necessary, the order of _color_priorities can be manually modified
        # after all tags have been defined.
        if tag.fg is not None or tag.bg is not None:
            self._color_priorities.append(tag)

        for key in [tag.name] + tag.aliases:
            if key in self._tags:
                raise Exception('tag "%s" already exists' % key)
            self._tags[key] = tag


class Tag:
    def __init__(self, name, description, aliases=None, score=0,
                 bg=None, fg=None):
        self.name = name
        self.description = description
        self.aliases = aliases or []
        self.score = score
        self.bg = bg
        self.fg = fg

        self._attr = None

    def get_attr(self):
        if self._attr is None:
            fg = self.fg
            if fg is None:
                fg = color.WHITE
            bg = self.bg
            if bg is None:
                bg = color.DEFAULT
            self._attr = color.get_color(fg, bg)
        return self._attr

    def __str__(self):
        return self.name

    def __repr__(self):
        return 'Tag(%r)' % (self.name,)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == other
        return self.name == other.name

    def __ne__(self, other):
        return self.name != other.name


class TagPrefix:
    def __init__(self, prefix, description, score=0):
        self.prefix = prefix
        self.description = description
        self.score = score

    def create_tag(self, suffix):
        """
        Create a new Tag using this prefix, with the specified suffix.
        """
        tag_name = self.prefix + suffix
        tag_desc = self.description.format(name=suffix)
        return Tag(tag_name, tag_desc, score=self.score)


class MetaTag(Tag):
    '''
    A tag based on whether or not other tags are defined.
    '''
    def __init__(self, name, description, meta=None, **kwargs):
        super().__init__(name, description, **kwargs)
        self.meta = meta or []
        if isinstance(self.meta , str):
            self.meta = [self.meta]

    def match(self, msg, tags):
        if self.meta is None:
            raise AssertionError('MetaTags must either define self.meta, '
                                 'or override check_match()')

        for other in self.meta:
            if other in tags:
                return True
        return False
