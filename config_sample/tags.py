#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from amt import color
import amt.tag

tags = amt.tag.TagDictionary()

#
# Tags for message state
#
tags.new_tag('archived', 'Mail has been archived')


#
# Tags based on the message recipients
#
tags.new_tag('mentions-me', 'Mentions my name', score=100)
tags.new_tag('to-me', 'My address is in the To header', score=50)
tags.new_tag('cc-me', 'My address is in the Cc header', score=30)

tags.new_tag_prefix('to-list-', 'Sent to the %{name} mailing list')


#
# Meta tags, in order of precedence.
# (They will be put into META_TAGS and COLOR_PRIORITIES in the order they
# are defined.)
#
tags.new_meta_tag('hipri', 'An important email I need to read',
                  meta=('mentions-me', 'my-tasks'))
