import logging
import re
import struct
from contextlib import suppress

import pefile
import yara

log = logging.getLogger()
log.setLevel(logging.INFO)

rule_source = """
rule Carbanak
{
    meta:
        author = "enzok"
        description = "Carnbanak sbox init"
        cape_type = "Carbanak Payload"
    strings:
        $sboxinit = {48 0F BE 02 4? 8D 05 [-] 4? 8D 4D ?? E8 [3] 00 33 F6 4? 8D 5D ?? 4? 63 F8 8B 45 ?? B? B1 E3 14 06} 
    condition:
        uint16(0) == 0x5A4D and any of them
}
"""

yara_rules = yara.compile(source=rule_source)


def decode_string(src, sbox):
    lenstr = len(src) - 4
    if lenstr < 0:
        lenstr = 0
    newstr = bytearray()
    lenblock = int(lenstr / 4)
    nb = 0
    rb = 0
    delta = 0
    n = 0
    i = 0
    while n < lenstr:
        if rb == 0:
            nb += 1
            if nb <= 4:
                delta = src[i] - 97
                i += 1
                rb = lenblock
            else:
                rb = lenstr - n
        elif rb > 0:
            rb -= 1
            c = src[i]
            if c < 32:
                min = 1
                max = 31
            elif c < 128:
                min = 32
                max = 127
            else:
                min = 128
                max = 255
            c = sbox[c]
            c -= delta
            if c < min:
                c = max - min + c
            n += 1
            newstr.append(c)
            i += 1
    return newstr


def extract_config(filebuf):
    cfg = {}
    pe = pefile.PE(data=filebuf)
    sbox_init_offset, sbox_delta, sbox_offset = 0, 0, 0
    matches = yara_rules.match(data=filebuf)
    if not matches:
        return
    for match in matches:
        if match.rule != "Carbanak":
            continue
        for item in match.strings:
            for instance in item.instances:
                if "$sboxinit" in item.identifier:
                    sbox_init_offset = int(instance.offset)
    if not sbox_init_offset:
        return
    sbox_delta = struct.unpack("I", filebuf[sbox_init_offset + 7 : sbox_init_offset + 11])[0]
    sbox_offset = pe.get_offset_from_rva(sbox_delta + pe.get_rva_from_offset(sbox_init_offset) + 11)
    sbox = bytes(filebuf[sbox_offset : sbox_offset + 128])
    data_sections = [s for s in pe.sections if s.Name.find(b".rdata") != -1]
    if not data_sections or not sbox:
        return None
    data = data_sections[0].get_data()
    items = data.split(b"\x00")
    c2_domains = []
    cfg_strings = []
    for item in items:
        with suppress(IndexError, UnicodeDecodeError, ValueError):
            dec = decode_string(item, sbox).decode("utf8")
            if dec:
                cfg_strings.append(dec)
                tlds = (".com", ".net", ".org", ".edu")
                if dec.endswith(tlds):
                    c2_domains.append(dec)
                ver = re.findall("^(\d+\.\d+)$", dec)[0]
                if ver:
                    cfg["version"] = ver
                # print(dec)
    if c2_domains:
        cfg["c2_domains"] = c2_domains
    # cfg["strings"] = cfg_strings
    return cfg


if __name__ == "__main__":
    import sys
    from pathlib import Path

    log.setLevel(logging.DEBUG)
    data = Path(sys.argv[1]).read_bytes()
    print(extract_config(data))
