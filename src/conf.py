import json
import os

GRAPH_CHAR_UTF8 = {}
GRAPH_CHAR_UTF8['degree'] = '°C'
GRAPH_CHAR_UTF8['horizontal'] = '─'
GRAPH_CHAR_UTF8['vertical'] = '│'
GRAPH_CHAR_UTF8['corner-top-left'] = '╭'
GRAPH_CHAR_UTF8['corner-top-right'] = '╮'
GRAPH_CHAR_UTF8['corner-bottom-left'] = '╰'
GRAPH_CHAR_UTF8['corner-bottom-right'] = '╯'
GRAPH_CHAR_UTF8['tree-down-right-mid'] = '├'
GRAPH_CHAR_UTF8['tree-down-right-end'] = '└'

GRAPH_CHAR_ASCII = {}
GRAPH_CHAR_ASCII['degree'] = ' C'
GRAPH_CHAR_ASCII['horizontal'] = '-'
GRAPH_CHAR_ASCII['vertical'] = '|'
GRAPH_CHAR_ASCII['corner-top-left'] = '+'
GRAPH_CHAR_ASCII['corner-top-right'] = '+'
GRAPH_CHAR_ASCII['corner-bottom-left'] = '+'
GRAPH_CHAR_ASCII['corner-bottom-right'] = '+'
GRAPH_CHAR_ASCII['tree-down-right-mid'] = '+'
GRAPH_CHAR_ASCII['tree-down-right-end'] = '+'

CHAR_MODE_ASCII = "ascii"
CHAR_MODE_UTF8 = "utf8"

def print_sample(graph_char):
    print("> {}{}{} <".format(graph_char['corner-top-left'], graph_char['horizontal'], graph_char['corner-top-right']))
    print("> {}{}{} <".format(graph_char['vertical'], ' ', graph_char['vertical']))
    print("> {}{}{} <".format(graph_char['corner-bottom-left'], graph_char['horizontal'], graph_char['corner-bottom-right']))

def get_char_mode():
    print("Initial configuration of Jill")
    print("Depending on how you access Jill,")
    print("UTF-8 characters might or might not be supported")
    print("Check which of the two you see at all or which looks better:")
    print("-------------------")
    print("1. UTF-8")
    try:
        print_sample(GRAPH_CHAR_UTF8)
    except:
        print("Ooops, UTF-8 failed. Guess that's not an option")
    print("-------------------")
    print("2. ASCII")
    print_sample(GRAPH_CHAR_ASCII)
    print("-------------------")
    c = None
    while c not in ['u', 'a']:
        c = input("Please enter u or a (for UTF-8 or ASCII):")
    return {'u' : CHAR_MODE_UTF8, 'a' : CHAR_MODE_ASCII}[c]


CONF_PATH = os.path.expanduser("~/.jill")
if os.path.exists(CONF_PATH):
    with open(CONF_PATH) as f:
        CONF = json.loads(f.read())
else:
    char_mode = get_char_mode()
    # Defaults if no conf available
    CONF = {
        'max-width' : 800,
        'max-height' : 400,
        'max' : 10000,
        'char-mode' : char_mode
    }
    with open(CONF_PATH, 'w') as f:
        f.write(json.dumps(CONF, indent=2))


CHAR_MODE = CONF['char-mode']


GRAPH_CHAR = {}
if CHAR_MODE == CHAR_MODE_UTF8:
    GRAPH_CHAR = GRAPH_CHAR_UTF8
elif CHAR_MODE == CHAR_MODE_ASCII:
    GRAPH_CHAR = GRAPH_CHAR_ASCII
else:
    raise Exception("Unexpected CHAR_MODE '{}'".format(CHAR_MODE))

BATTERY_INFO = [
    ['charge_full', 'charge_now'],
    ['capacity', 'capacity_smb']
]
