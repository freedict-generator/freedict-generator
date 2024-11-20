import json, os, shutil, sys, tarfile
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ElementTree
from xml.etree.ElementTree import Element
from typing import Optional, Dict, List

class DictSense:
    def __init__(self):
        self.quotes: Optional[List[str]] = None
        self.defs:   Optional[List[str]] = None

class DictEntry:
    def __init__(self):
        self.orth:   Optional[List[str]] = None
        self.pron:   Optional[List[str]] = None
        self.gen:    Optional[List[str]] = None
        self.pos:    Optional[List[str]] = None
        self.senses: Optional[List[str]] = None

def http_get(url):
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req)
    return resp.read()

def http_download(url, path):
    with open(path, "wb") as file:
        file.write(http_get(url))

def get_freedict_database():
    return json.loads(http_get("https://freedict.org/freedict-database.json"))

def load_freedict_database(filename):
    return json.load(open(filename))

def create_pair(src_lang, dst_lang):
    # convert to more common iso-639-1
    # https://en.wikipedia.org/wiki/List_of_ISO_639_language_codes
    map = {
        "afr": "af",
        "ara": "ar",
        "bre": "br",
        "bul": "bg",
        "cat": "ca",
        "ces": "cs",
        "cym": "cy",
        "dan": "da",
        "deu": "de",
        "ell": "el",
        "eng": "en",
        "epo": "eo",
        "fin": "fi",
        "fra": "fr",
        "gla": "gd",
        "gle": "ga",
        "hin": "hi",
        "hrv": "hr",
        "hun": "hu",
        "ind": "id",
        "isl": "is",
        "ita": "it",
        "jpn": "ja",
        "kur": "ku",
        "lat": "la",
        "lit": "lt",
        "mkd": "mk",
        "mlg": "mg",
        "nld": "nl",
        "nno": "nn",
        "nob": "nb",
        "nor": "no",
        "oci": "oc",
        "pol": "pl",
        "por": "pt",
        "rom": "ro", # should be ron
        "rus": "ru",
        "san": "sa",
        "slk": "sk",
        "slv": "sl",
        "spa": "es",
        "srp": "sr",
        "swe": "sv",
        "swh": "sw", # should be swa
        "tur": "tr",
        "wol": "wo",
        "zho": "zh",
    }
    if src_lang not in map:
        sys.stderr.write("error: mapping missing for %s" % src_lang)
        sys.exit(-1)
    if dst_lang not in map:
        sys.stderr.write("error: mapping missing for %s" % dst_lang)
        sys.exit(-1)

    return "%s-%s" % (map[src_lang], map[dst_lang])

def remove_namespace(element: Element):
    if element.tag.startswith("{http://www.tei-c.org/ns/1.0}"):
        element.tag = element.tag[len("{http://www.tei-c.org/ns/1.0}"):]
    else:
        sys.stderr.write("ERROR: %s\n" % element.tag)

def handle_includes(parent: Element, path):
    entries = []
    for subtree in parent:
        if subtree.tag == "{http://www.w3.org/2001/XInclude}include":
            href = subtree.get("href")
            root = ElementTree.parse(path + "/" + href).getroot()
            for entry in root:
                entries.append(entry)
    parent.clear()
    parent.extend(entries)

def handle_super_entries(parent: Element):
    for super in parent.findall(".//{http://www.tei-c.org/ns/1.0}superEntry"):
        for entry in super:
            parent.append(entry)
        parent.remove(super)

def preprocess(element: Element, path):
    # remove namespaces
    remove_namespace(element)

    # handle includes (for en-pl)
    if element.tag == "body":
        if len(element.findall(".//{http://www.w3.org/2001/XInclude}include")) > 0:
            handle_includes(element, path)

    # handle super entries
    if element.tag == "body":
        if len(element.findall(".//{http://www.tei-c.org/ns/1.0}superEntry")) > 0:
            handle_super_entries(element)

    # process leaf nodes
    for child in element:
        preprocess(child, path)

    return element

def collect_sense(element: Element, sense: DictSense, prefix):
    # push
    prefix.append(element.tag)
    path = ".".join(prefix)

    if path == "entry.sense.cit.quote":
        if sense.quotes is None:
            sense.quotes = [element.text]
        else:
            sense.quotes.append(element.text)
    elif path == "entry.sense.sense.def":
        if sense.defs is None:
            sense.defs = [element.text]
        else:
            sense.defs.append(element.text)

    # process leaf
    for child in element:
        collect_sense(child, sense, prefix)

    # pop
    prefix.pop()

def collect(element: Element, output: DictEntry, prefix):
    # push
    prefix.append(element.tag)
    path = ".".join(prefix)

    if path == "entry.form.orth":
        if element.text is not None: # <form><hi> data dropped
            if output.orth is None:
                output.orth = [element.text]
            else:
                output.orth.append(element.text)
    elif path == "entry.form.pron":
        if element.text is not None:
            if output.pron is None:
                output.pron = [element.text]
            else:
                output.pron.append(element.text)
    elif path == "entry.gramGrp.gen":
        if output.gen is None:
            output.gen = [element.text]
        else:
            output.gen.append(element.text)
    elif path == "entry.gramGrp.pos":
        if element.text is not None:
            if output.pos is None:
                output.pos = [element.text]
            else:
                if element.text not in output.pos:
                    output.pos.append(element.text)
    elif path == "entry.sense":
        prefix.pop()
        sense = DictSense()
        collect_sense(element, sense, prefix)
        if output.senses is None:
            output.senses = [sense]
        else:
            output.senses.append(sense)
        return

    # process leaf
    for child in element:
        collect(child, output, prefix)

    # pop
    prefix.pop()

def generate_orth(orth: str, entries: List[DictEntry], html_path: str):
    converted = orth.replace(" ", "_")
    if orth == converted:
        return generate_html(orth, entries, "%s/%s.html" % (html_path, orth))
    else:
        n1 = generate_html(orth, entries, "%s/%s.html" % (html_path, orth))
        n2 = generate_html(orth, entries, "%s/%s.html" % (html_path, converted))
        return n1 or n2

# waring: under windows some files (e.g., con.html) cannot be created
def generate_html(orth: str, entries: List[DictEntry], filename: str):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write('<!doctype html>\n')
            f.write('<html>\n')
            f.write('<head>\n')
            f.write('  <meta charset="utf-8">\n')
            f.write('  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
            f.write('  <title>FreeDicts</title>\n')
            f.write('  <link rel="stylesheet" href="dict.css">\n')
            f.write('  <link rel="icon" href="../favicon.ico">\n')
            f.write('</head>\n')
            f.write('<body>\n')

            # content
            for index, entry in enumerate(entries, start=1):
                # title
                if len(entries) == 1:
                    f.write(f'  <h3>{orth}</h3>\n')
                else:
                    f.write(f'  <h3>{orth}<sup>{index}</sup></h3>\n')
                # pronunciation
                if entry.pron:
                    f.write('  <span class="pron">' + ' '.join(entry.pron) + '</span><br/>\n')
                # pos & gen
                pos_gen = ""
                if entry.pos:
                    pos_gen += '<span class="pos">' + ' '.join(['[%s]' % pos for pos in entry.pos]) + '</span>'
                if entry.pos and entry.gen:
                    pos_gen += ' '
                if entry.gen:
                    pos_gen += '<span class="gen">' + ' '.join(entry.gen) + '</span>'
                # senses
                if entry.senses:
                    for sense_index, sense in enumerate(entry.senses, start=1):
                        f.write(f'  <b>{sense_index}. </b>{pos_gen}<br/>\n')
                        if sense.quotes:
                            for quote in sense.quotes:
                                f.write(f'  <p class="quote">{quote}</p>\n')
                        if sense.defs:
                            for defn in sense.defs:
                                f.write(f'  <p class="def">- {defn}</p>\n')
            f.write('</body>\n')
            f.write('</html>\n')
            return 1
    except (FileNotFoundError, OSError):
        sys.stderr.write("warn: failed to create file %s\n" % filename)
        return 0

if __name__ == "__main__":
    if len(sys.argv) == 1:
        database = get_freedict_database()
    elif len(sys.argv) == 3 and sys.argv[1] == "-f":
        database = load_freedict_database(sys.argv[2])
    else:
        sys.stderr.write("usage: python freedict-generator-lite.py [-f freedict-database.json]")
        sys.exit(-1)

    dicts = {}
    for dict in database:
        # skip freedict tools
        if "software" in dict:
            continue

        # skip dict: central kurdish (ku) to northern kurdish (ku)
        if dict["name"] == "ckb-kmr":
            continue

        # skip lang: khasi (not in iso-639-1)
        if dict["name"].startswith("kha"):
            continue

        # skip lang: asturian (not in iso-639-1)
        if dict["name"].endswith("ast"):
            continue

        # create prefix
        src_lang = dict["name"].split("-")[0]
        dst_lang = dict["name"].split("-")[1]
        pair = create_pair(src_lang, dst_lang)

        for release in dict["releases"]:
            if release["platform"] == "src":
                tei_path  = "temp/%s/%s.tei" % (dict["name"], dict["name"])
                base_path = "temp/%s" % dict["name"]
                html_path = "html/%s" % pair
                dicts[pair] = {}

                # download dict
                url = release["URL"]
                version = release["version"]
                path = "data/freedict-%s-%s.tar.xz" % (pair, version)
                if os.path.isfile(path):
                    pass # dict with specific version exists
                else:
                    http_download(url, path)
                    sys.stderr.write("%s\n" % path)

                # extract
                with tarfile.open(path, "r:xz") as tar:
                    tar.extractall(path="temp")

                # create output dir
                os.makedirs(html_path, exist_ok=True)

                # preprocess
                tree = ElementTree.parse(tei_path)
                root = tree.getroot()
                text = root.find("tei:text", {"tei": "http://www.tei-c.org/ns/1.0"})
                body = text.find("tei:body", {"tei": "http://www.tei-c.org/ns/1.0"})
                body = preprocess(body, base_path)

                entries: Dict[str, List[DictEntry]] = {}

                for element in body:
                    if element.tag == "entry":
                        # collect data
                        entry = DictEntry()
                        collect(element, entry, [])

                        # mergy entries by orth
                        if entry.orth is not None:
                            for orth in entry.orth:
                                if orth in entries:
                                    entries[orth].append(entry)
                                else:
                                    entries[orth] = [entry]

                # generate html
                sys.stderr.write("generate %s\n" % html_path)
                total = len(entries)
                succ = 0
                for orth in sorted(entries.keys()):
                    succ += generate_orth(orth, entries[orth], html_path)
                sys.stderr.write(" - %s: %.2f%% entries generated\n" % (pair, succ * 100.0 / total))

                # copy css
                shutil.copy("dict.css", "%s/dict.css" % html_path)