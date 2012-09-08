#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import weakref


class WeakrefContainer:
    def __init__(self):
        self.__items = {}

    def add(self, item):
        assert item is not None

        def _item_destroyed(ref):
            del self.__items[ref_id]

        ref = weakref.ref(item, _item_destroyed)
        ref_id = id(ref)
        self.__items[ref_id] = ref

    def __iter__(self):
        for ref in self.__items.values():
            item = ref()
            if item is not None:
                yield item
