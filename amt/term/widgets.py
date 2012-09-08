#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
from .terminal import Region
from .util import WeakrefContainer


class Drawable:
    def __init__(self, param):
        if isinstance(param, tuple):
            # A value returned by Drawable.subdrawable()
            self.__parent = param[0]
            self.__region = param[1]
        elif isinstance(param, Region):
            self.__parent = None
            self.__region = param
        elif isinstance(param, Drawable):
            self.__parent = param
            self.__region = param.region

        self.__visible = True
        self.__children = WeakrefContainer()
        self.__region.on_resize = self._on_resize

        if self.__parent:
            # If we have a parent, add ourself to its children.
            # It's redarw mechanism should handle redrawing us too.
            self.__parent.__children.add(self)

    def _redraw(self):
        raise NotImplementedError('_redraw() must be implemented '
                                  'by subclasses')

    def on_resize(self):
        # subclasses may implement on_resize() if they need to adjust
        # any state on a resize event.
        # on_resize() will be called before the drawable is redrawn.
        pass

    @property
    def parent(self):
        return self.__parent

    @property
    def region(self):
        return self.__region

    @property
    def term(self):
        return self.__region.term

    def redraw(self, flush=True):
        assert self.visible
        self._redraw()
        if flush:
            self.term.flush()

    def subregion(self, x, y, width=0, height=0):
        return self.region.region(x=x, y=y, width=width, height=height)

    def subdrawable(self, x, y, width=0, height=0):
        region = self.region.region(x=x, y=y, width=width, height=height)
        return (self, region)

    def get_visible(self):
        return self.__visible

    def set_visible(self, visible):
        if visible == self.__visible:
            return

        self._update_visibility(visible)
        if visible:
            self.redraw()

    visible = property(get_visible, set_visible)

    def _update_visibility(self, value):
        self.__visible = value
        for child in self.__children:
            child._update_visibility(value)

    def _on_resize(self):
        # Call self.on_resize() to let subclasses update state if necessary
        self.on_resize()

        # If we have a parent, it will handle redrawing us.
        # Otherwise we need to call redraw() ourselves.
        if self.visible:
            self.redraw(flush=False)


class ListSelection(Drawable):
    '''
    A ListSelection displays a list of items, with one item selected.

    This widget supports changing the selected item, and paging when the list
    is too long to fit in the region.
    '''
    def __init__(self, region):
        super(ListSelection, self).__init__(region)
        self.page_start = 0
        self.cur_idx = 0

    def get_num_items(self):
        '''
        Get the number of items being displayed.
        '''
        raise NotImplementedError('get_num_items() must be implemented '
                                  'by subclasses of ListSelection')

    def get_item_format(self, item_idx, selected):
        '''
        Return a tuple of (format_string, args, kwargs) to use for
        rendering the item at the specified index.

        The selected argument specifies if this item is selected or not.
        In general, the selected item should be rendered differently than
        unselected items, so the user can tell which item is selected.
        '''
        raise NotImplementedError('get_item_format() must be implemented '
                                  'by subclasses of ListSelection')

    def move_down(self, amount=1, flush=True):
        self.move(amount, flush=flush)

    def move_up(self, amount=1, flush=True):
        self.move(-amount, flush=flush)

    def page_down(self, amount=1.0, flush=True):
        line_amount = int(self.region.height * amount)
        if amount > 0 and line_amount == 0:
            line_amount = 1
        elif amount < 0 and line_amount == 0:
            line_amount = -1
        self.move(line_amount, flush=flush)

    def page_up(self, amount=1.0, flush=True):
        self.page_down(-amount, flush=flush)

    def move(self, amount, flush=True):
        '''
        Adjust the item index by the specified amount.
        '''
        num_items = self.get_num_items()
        new_idx = self.cur_idx + amount
        if new_idx < 0:
            new_idx = 0
        elif new_idx >= num_items:
            new_idx = num_items - 1

        self.goto(new_idx, flush=flush)

    def goto(self, idx, flush=True):
        '''
        Go to the item at the specified index.
        '''
        if idx < 0:
            num_items = self.get_num_items()
            idx = max(0, num_items + idx)

        if idx == self.cur_idx:
            return

        old_idx = self.cur_idx
        self.cur_idx = idx
        page_changed = self._adjust_page()

        if not self.visible:
            return

        if page_changed:
            # redraw the entire region
            self.redraw(flush=False)
        else:
            # only redraw the 2 lines that changed
            old_line_idx = old_idx - self.page_start
            new_line_idx = self.cur_idx - self.page_start
            self.render_item(old_line_idx, old_idx)
            self.render_item(new_line_idx, self.cur_idx)

        if flush:
            self.region.term.flush()

    def _adjust_page(self):
        '''
        Adjust self.page_start to ensure that self.cur_idx is visible on the
        page.

        Returns True if self.page_start changed, and False if self.page_start
        did not need to be adjusted.
        '''
        if self.page_start > self.cur_idx:
            while self.page_start > self.cur_idx:
                self.page_start -= self.region.height
                if self.page_start < 0:
                    self.page_start = 0
                    break
            return True
        elif self.page_start + self.region.height <= self.cur_idx:
            while self.page_start + self.region.height <= self.cur_idx:
                self.page_start += self.region.height
            return True
        else:
            return False

    def on_resize(self):
        self._adjust_page()

    def _redraw(self):
        line_idx = 0
        item_idx = self.page_start
        num_items = self.get_num_items()
        while item_idx < num_items and line_idx < self.region.height:
            self.render_item(line_idx, item_idx)
            line_idx += 1
            item_idx += 1

        while line_idx < self.region.height:
            self.region.writeln(line_idx, '{=}')
            line_idx += 1

    def render_item(self, line_idx, item_idx):
        '''
        Render a single item.

        This calls get_item_format() to determine the format to use to
        display the item.

        Subclasses should normally override get_item_format(), and generally
        should not need to change render_item().
        '''
        assert self.visible

        selected = (item_idx == self.cur_idx)
        result = self.get_item_format(item_idx, selected)

        args = None
        kwargs = None
        if isinstance(result, str):
            fmt = result
        elif len(result) == 1:
            fmt = result[0]
        elif len(result) == 2:
            fmt = result[0]
            if isinstance(result[1], (list, tuple)):
                args = result[1]
            else:
                kwargs = result[1]
        elif len(result) == 3:
            fmt = result[0]
            args = result[1]
            kwargs = result[2]

        if not isinstance(fmt, str):
            raise Exception('get_item_format() must return a string format')
        if args is None:
            args = ()
        elif not isinstance(args, (list, tuple)):
            raise Exception('get_item_format() must return the args as a '
                            'tuple or list')
        if kwargs is None:
            kwargs = {}
        elif not isinstance(kwargs, dict):
            raise Exception('get_item_format() must return the kwargs as a '
                            'dictionary')

        self.region.vwriteln(line_idx, fmt, args, kwargs, hfill=True)


class FixedListSelection(ListSelection):
    '''
    FixedListSelection is a ListSelection object that displays the specified
    list of items.
    '''
    def __init__(self, region, items):
        super(FixedListSelection, self).__init__(region)
        self.items = items

    def get_num_items(self):
        return len(self.items)

    def get_item_format(self, item_idx, selected):
        item = self.items[item_idx]

        num_width = len(str(len(self.items)))
        fmt = '{idx:red:>%d} {item}' % (num_width,)
        kwargs = {'idx': item_idx, 'item': item}

        if selected:
            fmt = '{+:reverse}' + fmt
        return fmt, kwargs
