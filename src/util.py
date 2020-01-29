import json
import logging
import subprocess

MEM_UNITS = "B KB MB GB TB".split()

def partition(lst, chunk_size):
    result = []
    ix = 0
    while ix < len(lst):
        result.append(lst[ix:ix+chunk_size])
        ix += chunk_size
    return result

def read_single_line(path):
    try:
        with open(path, 'r') as f:
            data = f.read().replace('\n', '')
            return data
    except FileNotFoundError:
        # process no longer exists
        return None
    except OSError:
        # Could be empty file
        return None

def str_as_dict(txt, separator):
    result = {}
    for line in txt.splitlines():
        parts = line.split(separator)
        parts = [ p for p in parts if p]
        if len(parts) == 2:
            result[parts[0].strip()] = parts[1].strip()
        else:
            raise Exception("Can't split line '{}'".format(line))
    return result
    
def file_as_dict(file_path, separator=" "):
    with open(file_path) as f:
        return str_as_dict(f.read(), separator)

def command_output(cmds):
    proc = subprocess.Popen(cmds, stdout=subprocess.PIPE)
    proc.wait()
    out, err = proc.communicate()
    if err:
        logging.error(err)
        raise Exception("Failed to run '{}'".format(cmd))
    return out.decode("utf8")

def command_as_dict(cmd, separator=None):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    proc.wait()
    out, err = proc.communicate()
    if err:
        logging.error(err)
        raise Exception("Failed to run '{}'".format(cmd))
    return str_as_dict(out.decode("utf8"), separator)
    
def command_as_json(cmds):
    proc = subprocess.Popen(cmds, stdout=subprocess.PIPE)
    proc.wait()
    out, err = proc.communicate()
    if err:
        logging.error(err)
        raise Exception("Failed to run '{}'".format(cmds))
    return json.loads(out.decode("utf8"))

def time_to_str(t, include_seconds):
    seconds = t - 60 * int(t / 60)
    t = (t - seconds) / 60
    minutes = t - 60 * int(t / 60)
    t = (t - minutes) / 60
    hours = t - 24 * int(t / 24)
    if include_seconds:
        return "%.2d:%.2d:%.2d" % (hours, minutes, seconds)
    else:
        return "%.2d:%.2d" % (hours, minutes)

def format_memory(value, unit="B"):
    try:
        unit_index = MEM_UNITS.index(unit)
    except ValueError:
        return value

    while value > 10000 and unit_index < len(MEM_UNITS) - 1:
        value = value / 1024
        unit_index += 1
    return "{:2} {}".format(round(value, 2), MEM_UNITS[unit_index])

def intersect_y(x1, y1, x2, y2, y_target):
    if y1 == y2 or x1 == x2:
        return None
    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1
    x = (y_target - b) / m
    return x

def split_evenly(amount_to_distribute, part_count):
    """Creates a list of integer of len part_count.
        The integers sum up to amount_to_distribute"""
    if part_count == 0:
        return []
    remaining = amount_to_distribute
    min_chunk = amount_to_distribute // part_count
    result = []
    for i in range(0, part_count):
        result.append(min_chunk)
        remaining -= min_chunk
    if remaining > part_count:
        raise Exception("Remaining is %d, part_count is %d" % (remaining, part_count))
    if remaining > 0:
        delta = part_count // remaining
        i = 0
        while i < part_count:
            if remaining > 0:
                result[i] += 1
                remaining -= 1
            i += delta
    if remaining > 0:
        raise Exception("Split evenly failed: Have %d left in the end" % remaining)
    return result


class Dispatcher:
    def __init__(self, default_handler):
        self.default_handler = default_handler
        self.handlers = {}
        self.keys = []

    def register(self, clazz, handler):
        for i in range(0, len(self.keys)):
            if self.keys[i] in clazz.__bases__:
                self.keys.insert(i, clazz)
                self.handlers[clazz] = handler
                return
        self.keys.append(clazz)
        self.handlers[clazz] = handler

    def get_handler(self, obj):
        for k in self.keys:
            if isinstance(obj, k):
                return self.handlers[k]
        return self.default_handler

# Decorator function
def dispatcher(default_handler):
    d = Dispatcher(default_handler)
    class DecoratorDispatcher:
        def register(self, clazz):
            def register_impl(specific_handler):
                d.register(clazz, specific_handler)
            return register_impl
        def __call__(self, *pos_args, **kw_args):
            d.get_handler(pos_args[0])(*pos_args, **kw_args)
    return DecoratorDispatcher()


class Packet:
    def __init__(self):
        self.items = []
        self.total = 0

    def __len__(self):
        return len(self.items)

    def append(self, item, size):
        self.items.append(item)
        self.total += size

class Filler:
    def __init__(self, max_packet_size):
        self.max_packet_size = max_packet_size
        self.packets = []

    def push_it(self):
        self.packets.append(Packet())
        return self.packets[len(self.packets) - 1]
    def add(self, item, size):
        if len(self.packets) == 0:
            self.push_it()
        last = self.packets[len(self.packets) - 1]
        if len(last) == 0:
            last.append(item, size)
            if last.total >= self.max_packet_size:
                self.push_it()
        else:
            if last.total + size > self.max_packet_size:
                last = self.push_it()
            last.append(item, size)
            
    def to_lists(self):
        outer = []
        for p in self.packets:
            outer.append(p.items)
        return outer

class LinkedListItem:
    def __init__(self, obj):
        self.obj = obj
        self.next = None
        self.prev = None

class LinkedList:
    def __init__(self):
        self.__current = None

    def __bool__(self):
        return bool(self.__current)

    def add(self, obj):
        if self.__current:
            lli = LinkedListItem(obj)
            lli.next = self.__current.next
            lli.prev = self.__current
            lli.next.prev = lli
            lli.prev.next = lli
            self.__current = lli
        else:
            lli = LinkedListItem(obj)
            lli.prev = lli
            lli.next = lli
            self.__current = lli

    def current(self):
        return self.__current.obj
    def next(self):
        self.__current = self.__current.next
        return self.__current.obj
    def prev(self):
        self.__current = self.__current.prev
        return self.__current.obj
    def items(self):
        result = list()
        t = self.__current
        result.append(t.obj)
        t = t.next
        while t != self.__current:
            result.append(t.obj)
            t = t.next
        return result

class ValueCounter:
    def __init__(self, some_dict):
        self.count = {}
        for v in some_dict.values():
            if v in self.count:
                self.count[v] += 1
            else:
                self.count[v] = 1
