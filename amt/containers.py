#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import weakref


class WeakrefSet:
    def __init__(self):
        self.__items = {}

    def add(self, item):
        assert item is not None

        def _item_destroyed(ref):
            del self.__items[ref_id]

        ref = weakref.ref(item, _item_destroyed)
        ref_id = id(ref)
        self.__items[ref_id] = ref

    def remove(self, item):
        '''
        Remove an item from the container.

        Note that this is O(n) at the moment.  (This is fixable by adding
        a second index, but probably not worth the effort at the moment,
        since WeakrefSet is only used for very small lists.)
        '''
        assert item is not None

        for ref in self.__items.values():
            if item == ref():
                ref_id = id(ref)
                del self.__items[ref_id]
                return
        raise KeyError('no such item in the container')

    def __iter__(self):
        # Copy the values in case they change while we are iterating
        weak_refs = list(self.__items.values())
        for ref in weak_refs:
            item = ref()
            if item is not None:
                yield item
