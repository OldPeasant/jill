
import curses
import datetime
import logging
import traceback

from .conf import CONF, GRAPH_CHAR
from .util import Dispatcher, dispatcher, Filler, split_evenly, LinkedList

        

class LayoutConstraint:
    def __init__(self,
            min_width = 0, min_height = 0,
            stretch_x = False, stretch_y = True):
        self.min_width = min_width
        self.min_height = min_height
        self.stretch_x = stretch_x
        self.stretch_y = stretch_y

class Component:
    def __init__(self):
        self.__parent = None
        self.x = 0
        self.y = 0
        self.w = 0
        self.h = 0
        self.__min_width = 0
        self.__min_height = 0
        self.__stretch_x = False
        self.__stretch_y = False
        self.__layout_valid = False
        self.can_focus = False
        self.has_focus = False

    def set_cursor_safe(self, stdscr, x, y):
        try:
            stdscr.addstr(y, x, "")
        except:
            pass

    def set_cursor(self, stdscr, x, y):
        set_cursor_safe(stdscr, x, y)

    def update_from_model(self):
        # Default empty implementation
        pass

    def layout(self, w, h):
        self.w = w
        self.h = h
        self.layout_valid = True

    def write_safe(self, stdscr, x, y, max_x, max_y, txt, mode=curses.A_NORMAL):
        if y >= max_y or x > max_x:
            return
        try:
            stdscr.addstr(y, x, txt[:(max_x - x - 1)], mode)
        except:
            logging.info("Writing {}/{} {} failed".format(y, x, txt))

    @property
    def parent(self):
        return self.__parent

    @parent.setter
    def parent(self, p):
        if self.__parent is not None:
            raise Exception("%s already has a parent" % str(self))
        self.__parent = p

    @property
    def min_width(self):
        return self.__min_width

    @min_width.setter
    def min_width(self, w):
        if self.__min_width != w:
            self.__min_width = w
            self.layout_valid = False

    @property
    def min_height(self):
        return self.__min_height

    @min_height.setter
    def min_height(self, h):
        if self.__min_height != h:
            self.__min_height = h
            self.layout_valid = False

    @property
    def stretch_x(self):
        return self.__stretch_x

    @stretch_x.setter
    def stretch_x(self, s):
        if self.__stretch_x != s:
            self.__stretch_x = s
            self.layout_valid = False

    @property
    def stretch_y(self):
        return self.__stretch_y

    @stretch_y.setter
    def stretch_y(self, s):
        if self.__stretch_y != s:
            self.__stretch_y = s
            self.layout_valid = False

    @property
    def layout_valid(self):
        return self.__layout_valid

    @layout_valid.setter
    def layout_valid(self, v):
        if self.__layout_valid != v:
            self.__layout_valid = v
            if self.__parent and not v:
                self.__parent.layout_valid = False


class Container(Component):
    def __init__(self):
        super(Container, self).__init__()
        self.__components = []

    @property
    def components(self):
        return list(self.__components)

    def add(self, component):
        self.__components.append(component)
        component.parent = self
    def update_from_model(self):
        for c in self.__components:
            c.update_from_model()

    def write(self, stdscr, x, y, max_x, max_y):
        for child in self.__components:
            child.write(stdscr, x + child.x, y + child.y, min(x + child.x + child.w + 1, max_x), min(y + child.y + child.h + 1, max_y))

class HorizontalFlow(Container):

    def __init__(self):
        super(HorizontalFlow, self).__init__()

    def __str__(self):
        return "  HorizontalFlow"

    @property
    def stretch_y(self):
        for c in self.components:
            if c.stretch_y:
                return True
        return False

    @stretch_y.setter
    def stretch_y(self, s):
        raise Exception("Can't set stretch_y property on HorizontalFlow. It's determined by the stretch_y property of the contents")

    @property
    def min_height(self):
        m = 0
        for c in self.components:
            if m < c.min_height:
                m = c.min_height
        return m

    @min_height.setter
    def min_height(self, h):
        raise Exception("Property min_height is read-only in HorizontalFlow: \
                        Set min_height in contents")

    def layout(self, w, h):
        self.w = w
        self.h = h
        sum_min_width = 0
        count_stretchable_horizontal = 0
        for c in self.components:
            sum_min_width += c.min_width
            if c.stretch_x:
                count_stretchable_horizontal += 1
        to_distribute = max(0, w - sum_min_width)
        to_distribute_for_component = split_evenly(to_distribute, count_stretchable_horizontal)

        dist_index = 0
        x = 0
        for c in self.components:
            c.x = x
            c.y = 0
            new_width = c.min_width
            if c.stretch_x:
                new_width += to_distribute_for_component[dist_index]
                dist_index += 1
            c.w = new_width
            c.h = h
            c.layout(c.w, c.h)
            x += c.w
        self.layout_valid = True

class VerticalFlow(Container):

    def __str__(self):
        return "  VerticalFlow"

    def layout(self, w, h):
        self.w = w
        self.h = h
        sum_min_height = 0
        count_stretchable_vertical = 0
        for c in self.components:# all VerticalFlows
            sum_min_height += c.min_height
            if c.stretch_y:
                count_stretchable_vertical += 1
        to_distribute = max(0, h - sum_min_height)
        to_distribute_for_component = split_evenly(to_distribute, count_stretchable_vertical)

        dist_index = 0
        y = 0
        for c in self.components:
            row_height = c.min_height
            if c.stretch_y:
                row_height += to_distribute_for_component[dist_index]
                dist_index += 1
            c.x = 0
            c.y = y
            c.layout(w, row_height)
            y += row_height
        self.layout_valid = True

class Canvas(Component):
    def __init__(self):
        super(Canvas, self).__init__()
        self.clear()

    def layout(self, w, h):
        self.w = w
        self.h = h
        self.layout_valid = True

    def clear(self):
        self.buffer = [ [x] * CONF['max-width'] for x in [" "] * CONF['max-height']]

    def buffer_lines(self):
        lines = []
        for b in self.buffer:
            lines.append("".join(b))
        return lines

    def addstr(self, row, col, txt):
        self.buffer[row][col:(col+len(txt))] = list(txt)

    @property
    def components(self):
        return []
# Check these characters for borders
# ┘
# ┐
# ┌
# └
    
class TitledBorder(Container):
    def __init__(self, title, contained_component):
        super(TitledBorder, self).__init__()
        if contained_component.parent:
            raise Exception("Contained component {} already has parent {}".format(contained_component, contained_component.parent))
        self.title = title
        self.contained_component = contained_component
        self.add(contained_component)
        self.clear()

    def __str__(self):
        return "    TitledBorder[{}]".format(self.title)

    def clear(self):
        pass
        #self.buffer = [ [x] * CONF['max-width'] for x in [" "] * CONF['max-height']]
        #self.__draw_border()
        #self.addstr(0, 2, " {} ".format(self.title))

    def addstr(self, row, col, txt):
        self.buffer[row][col:(col+len(txt))] = list(txt)

    def __draw_border(self, stdscr, x, y, max_x, max_y):
        
        for rel_x in range(0, self.w):
            self.write_safe(stdscr, x + rel_x, y, max_x, max_y, GRAPH_CHAR['horizontal'])
            self.write_safe(stdscr, x + rel_x, y + self.h - 1, max_x, max_y, GRAPH_CHAR['horizontal'])
        for rel_y in range(0, self.h):
            self.write_safe(stdscr, x, y + rel_y, max_x, max_y, GRAPH_CHAR['vertical'])
            self.write_safe(stdscr, x + self.w - 1, y + rel_y, max_x, max_y, GRAPH_CHAR['vertical'])
        self.write_safe(stdscr, x, y, max_x, max_y, GRAPH_CHAR['corner-top-left'])
        self.write_safe(stdscr, x, y + self.h - 1, max_x, max_y, GRAPH_CHAR['corner-bottom-left'])
        self.write_safe(stdscr, x + self.w - 1, y, max_x, max_y, GRAPH_CHAR['corner-top-right'])
        self.write_safe(stdscr, x + self.w - 1, y + self.h - 1, max_x, max_y, GRAPH_CHAR['corner-bottom-right'])

        if self.contained_component.can_focus and self.contained_component.has_focus:
            style = curses.A_REVERSE
        else:
            style = curses.A_NORMAL
        self.write_safe(stdscr, x + 2, y, max_x, max_y, " {} ".format(self.title), style)
    def layout(self, w, h):
        cc = self.contained_component
        cc.x = 1
        cc.y = 1
        cc.layout(w - 2, h - 2)
        self.clear()
        self.layout_valid = True

    def write(self, stdscr, x, y, max_x, max_y):
        self.__draw_border(stdscr, x, y, max_x, max_y)
        super(TitledBorder, self).write(stdscr, x, y, max_x, max_y)

    @property
    def min_width(self):
        return self.contained_component.min_width + 2

    @min_width.setter
    def min_width(self, w):
        raise Exception("Can't set min_width of TitledBorder. Set it in contained component instead")

    @property
    def min_height(self):
        return self.contained_component.min_height + 2

    @min_height.setter
    def min_height(self, h):
        raise Exception("Can't set min_height of TitledBorder. Set it in contained component instead")

    @property
    def layout_valid(self):
        return self.contained_component.layout_valid

    @layout_valid.setter
    def layout_valid(self, v):
        if self.parent and not v:
            self.parent.layout_valid = False

    @property
    def stretch_x(self):
        return self.contained_component.stretch_x

    @stretch_x.setter
    def stretch_x(self, s):
        self.contained_component.stretch_x = s

    @property
    def stretch_y(self):
        return self.contained_component.stretch_y

    @stretch_y.setter
    def stretch_y(self, s):
        self.contained_component.stretch_y = s

class TableColumn:
    def __init__(self, caption, min_width=None, max_width=None, visible=True):
        self.caption = caption
        self.min_width = min_width
        self.max_width = max_width
        self.visible = visible

class Table(Canvas):
    def __init__(self, columns=None, grower=True, row_limit=None,
                       always_highlight_selection=False, show_header=False):
        super(Table, self).__init__()
        self.columns = []
        if columns:
            self.columns.extend(columns)
        self.grower = grower
        self.row_limit = row_limit
        self.always_highlight_selection = always_highlight_selection
        self.show_header = show_header
        self._data = []
        self.col_widths = []
        for c in self.columns:
            self.col_widths.append(c.min_width if c.min_width and c.visible else 0)
        self.selected_row_index = 0

    def set_cursor(self, stdscr, x, y):
        """Don't set the cursor in a table"""
        pass

    def handle_key(self, key):
        header_offset = 1 if self.show_header else 0
        if key == ord('j') or key == curses.KEY_DOWN:
            self.selected_row_index += 1
            if self.selected_row_index >= len(self._data):
                self.selected_row_index = len(self._data) - 1
        elif key == ord('k') or key == curses.KEY_UP:
            self.selected_row_index -= 1
        if self.selected_row_index < 0:
            self.selected_row_index = 0

    def __str__(self):
        return "      "+ self.__class__.__name__

    def layout(self, w, h):
        self.w = w
        self.h = h
        self.layout_valid = True

    def _extend_data_list(self, row_index, col_index):
        while len(self._data) <= row_index:
            self._data.append([])
        while len(self._data[row_index]) <= col_index:
            self._data[row_index].append("")
        while len(self.col_widths) <= col_index:
            self.col_widths.append(0)
            self.columns.append(TableColumn(""))

    def clear_table(self):
        self._data = []
        #self.scroll_offset = 0

    def set_value(self, row, column, value):
        self._extend_data_list(row, column)
        self._data[row][column] = value
        if self.columns[column].visible and len(value) > self.col_widths[column]:
            self.col_widths[column] = len(value)
            if self.columns[column].max_width and self.columns[column].max_width < self.col_widths[column]:
                self.col_widths[column] = self.columns[column].max_width
            sum = 0
            for s in self.col_widths:
                sum += s
            self.min_width = sum + len(self.col_widths) - 1
        if self.row_limit:
            self.min_height = min(self.row_limit, len(self._data))
        else:
            self.min_height = len(self._data)

    def write(self, stdscr, x, y, max_x, max_y):
        if self.show_header:
            header_offset = 1
            cell_x = x
            for col_index, col in enumerate(self.columns):
                if col.visible:
                    txt = self.columns[col_index].caption.ljust(self.col_widths[col_index] + 1)
                    self.write_safe(stdscr, cell_x, y, max_x, max_y, txt, curses.A_REVERSE)
                cell_x += self.col_widths[col_index] + (1 if col.visible else 0)
        else:
            header_offset = 0
        scroll_offset = max(0, self.selected_row_index - self.h + header_offset + 1)
        for row_index, row in enumerate(self._data):
            if row_index - scroll_offset >= 0 and row_index - scroll_offset < self.h - header_offset:
                style = curses.A_NORMAL
                if self.has_focus:
                    # selected row as A_REVERSE
                    if row_index == self.selected_row_index:
                        style = curses.A_REVERSE
                else:
                    if self.always_highlight_selection:
                        # selected row and the one above as underline
                        if row_index == self.selected_row_index or row_index + 1 == self.selected_row_index:
                            style = curses.A_UNDERLINE
                    
                cell_y = y + row_index - scroll_offset + header_offset
                cell_x = x
                for col_index, cell in enumerate(row):
                    if self.columns[col_index].visible:
                        txt = cell.ljust(self.col_widths[col_index] + 1)
                        self.write_safe(stdscr, cell_x, cell_y, max_x, max_y, txt, style)
                    cell_x += self.col_widths[col_index] + (1 if self.columns[col_index].visible else 0)

class Label(Canvas):
    def __init__(self, text, style=curses.A_NORMAL, width=None):
        super(Label, self).__init__()
        self.text = text
        self.style = style
        self.width = width

    def write(self, stdscr, x, y, max_x, max_y):
        if self.width:
            txt = self.text.ljust(self.width)
        else:
            txt = self.text
        txt = txt[:min(self.w, max_x - x)]
        self.write_safe(stdscr, x, y, max_x, max_y, txt, self.style)

class InputField(Canvas):
    def __init__(self, name=None):
        super(InputField, self).__init__()
        self.can_focus = True
        self.value = ""
        self.name = name
    def write(self, stdscr, x, y, max_x, max_y):
        mode = curses.A_REVERSE if self.has_focus else curses.A_NORMAL
        if len(self.value) > self.w:
            txt = self.value[(len(self.value)-self.w):]
        else:
            txt = self.value.ljust(self.w)
        txt = txt[:max_x - x]
        self.write_safe(stdscr, x, y, max_x, max_y, txt, mode)
    def set_cursor(self, stdscr, x, y):
        dx = min(self.w - 1, len(self.value))
        self.set_cursor_safe(stdscr, x + dx, y)
        
    def handle_key(self, key):
        if key == 263:
            self.value = self.value[:len(self.value)-1]
        elif key >= 32  and key <= 126: # 'normal' characters
            self.value += chr(key)

class FilterTable(Container):
    def __init__(self, table_columns, always_highlight_selection=False):
        super(FilterTable, self).__init__()
        self.columns = table_columns
        self.search_fields = []
        self.create_contents(always_highlight_selection)
        self.layout_valid = True


    def create_contents(self, always_highlight_selection):
        x = 0
        for c in self.columns:
            fld = InputField(c.caption)
            fld.x = x
            fld.y = 0
            fld.w = c.max_width
            fld.h = 1
            fld.layout_valid = True
            fld.can_focus = c.visible
            self.search_fields.append(fld)
            self.add(fld)
            x += c.max_width + (1 if c.visible else 0)

        self.table = Table(always_highlight_selection = always_highlight_selection, columns=self.columns, show_header = True)
        self.table.can_focus = True
        self.table.x = 0
        self.table.y = 1
        self.add(self.table)
        
    def clear_table(self):
        self.table.clear_table()

    def set_value(self, row, column, value):
        self.table.set_value(row, column, value)
    
    def search_values(self):
        result = {}
        for s in self.search_fields:
            result[s.name] = s.value
        return result

    def clear(self):
        self.buffer = [ [x] * CONF['max-width'] for x in [" "] * CONF['max-height']]
        self.addstr(0, 0, "*")

    def layout(self, w, h):
        self.w = w
        self.h = h
        self.table.h = h - 1
        self.table.w = w - 0
        self.layout_valid = True
        x = 0
        for i, s in enumerate(self.search_fields):
            col_width = self.table.col_widths[i]
            s.x = x
            s.w = col_width + 1
            x += s.w

def component_coordinates_to_str(c):
    return "(%d, %d)-(%d, %d)" % (c.x, c.y, c.x + c.w, c.y + c.h)

@dispatcher
def print_component_tree(something, lines, indent):
    lines.append(" " * indent + str(something))

@print_component_tree.register(Component)
def _(component, lines, indent):
    lines.append("%sComponent[%s]%s {layout %s}" % (" " * indent, component.__class__.__name__, component_coordinates_to_str(component), str(component.layout_valid)))

@print_component_tree.register(Container)
def _(container, lines, indent):
    lines.append("%sContainer[%s]%s {layout %s}" % (" " * indent, container.__class__.__name__, component_coordinates_to_str(container), str(container.layout_valid)))
    for c in container.components:
        print_component_tree(c, lines, indent + 1)

def print_full_component(component):
    return "\n".join(full_components_as_list(component))

def full_components_as_list(component):
    lines = []
    print_component_tree(component, lines, 0)
    return lines

class Controller:
    def __init__(self, tui):
        self.tui = tui

    def next_screen(self):
        self.tui.current_screen_index = (self.tui.current_screen_index + 1) % len(self.tui.screens)

class FocusManager():
    def __init__(self, root_component):
        self.focusable_components = LinkedList()
        self.__find_all_focusable(root_component)
        if self.focusable_components:
            self.focusable_components.next()
    def __find_all_focusable(self, comp):
        if comp.can_focus:
            self.focusable_components.add(comp)
        if isinstance(comp, Container):
            for child in comp.components:
                self.__find_all_focusable(child)
    def next(self):
        curr = self.focusable_components.current()
        if curr:
            curr.has_focus = False
            self.focusable_components.next().has_focus = True
    def prev(self):
        curr = self.focusable_components.current()
        if curr:
            curr.has_focus = False
            self.focusable_components.prev().has_focus = True

class Screen:
    def __init__(self, root_component):
        self.root_component = root_component
        self.focus_mgr = FocusManager(root_component)

    def __set_cursor(self, stdscr, x, y, components):
        last = components.pop()
        if len(components) > 0:
            self.__set_cursor(stdscr, x + last.x, y + last.y, components)
        else:
            last.set_cursor(stdscr, x + last.x, y + last.y)

    def write(self, stdscr):
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        self.root_component.write(stdscr, 0, 0, max_x, max_y)
        in_focus = self.focus_mgr.focusable_components.current()
        if in_focus:
            path = []
            p = in_focus
            while p:
                path.append(p)
                p = p.parent
            self.__set_cursor(stdscr, 0, 0, path)

    def focus_prev(self):
        if self.focus_mgr.focusable_components:
            self.focus_mgr.prev()

    def focus_next(self):
        if self.focus_mgr.focusable_components:
            self.focus_mgr.next()

    def handle_key(self, c):
        f = self.focus_mgr.focusable_components.items()
        if f:
            f[0].handle_key(c)

class Tui:
    def __init__(self, stdscr):
        self._stdscr = stdscr
        self._screens = []
        self._current_screen_index = -1
        self._controller = Controller(self)

    def add_screen(self, s):
        self._screens.append(s)
        s.controller = self._controller
        if self._current_screen_index < 0:
            self._current_screen_index = 0

    @property
    def current_screen(self):
        return self._screens[self._current_screen_index]

    def handle_key(self, c):
        sc = self.current_screen
        if c == curses.KEY_RESIZE:
            max_y, max_x = self._stdscr.getmaxyx()
            sc.resized(max_y, max_x)
        elif c == 9: # TAB
            sc.focus_next()
        elif c == 353: # SHIFT-TAB
            sc.focus_prev()
        elif c == -1: # Timeout, no key pressed
            #sc.time_tick()
            pass
        else: # let current screen decide what to do
            sc.handle_key(c)
        sc.time_tick()
        if not sc.view.layout_valid:
            sc.view.layout(sc.cols, sc.rows)
        #for l in full_components_as_list(sc.view):
        #    logging.info("==>{}".format(l))
        sc.write(self._stdscr)
        self._stdscr.refresh()
        
        
        #logging.info("==== Components that can get focus: ====")
        #for c in sc.focus_mgr.focusable_components.items():
        #    logging.info("  {}: {}".format(c, c.has_focus))
        #logging.info("========================================")

    def event_loop(self):
        self.handle_key(curses.KEY_RESIZE)
        while (True):
            try:
                c = self._stdscr.getch()
            except KeyboardInterrupt:
                return
            self.handle_key(c)


class curses_tui:

    def __init__(self, *, halfdelay):
        self.halfdelay = halfdelay

    def __enter__(self):
        logging.info("=============== START CURSES ===============")
        self.stdscr = curses.initscr()
        curses.noecho();
        curses.cbreak();
        self.stdscr.keypad(1)
        curses.halfdelay(self.halfdelay)
        return Tui(self.stdscr)

    def __exit__(self, ex_type, value, tb):
        if tb:
            logging.info("=============== CURSES FAILED ===============")
            logging.error("%s: %s" % (str(ex_type), str(value)))
            for l in traceback.format_tb(tb):
                for p in l.split("\n"):
                    if p:
                        logging.error(p)
        else:
            logging.info("=============== ENDEDS CURSES ===============")
        curses.nocbreak();
        self.stdscr.keypad(0);
        curses.echo()
        curses.endwin()



