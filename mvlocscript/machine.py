import json
import json5
from glob import glob
from pathlib import Path
import re
from mvlocscript.fstools import glob_posix
from mvlocscript.potools import readpo, writepo, StringEntry

        
def makeMTjson(lang, version):
    globpattern_original = 'locale/**/en.po'

    data_dict = {}
    data_dict['lang'] = lang
    data_dict['version'] = version
    dict_temp = {}
    for filepath_original in glob_posix(globpattern_original):
            dict_original, _, _ = readpo(filepath_original)
            dict_map = {}
            try:
                dict_hand, _, _ = readpo(f'locale/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}/{lang}.po')
                for key, entry in dict_original.items():
                     dict_map[entry.value] = dict_hand.get(key, '')
                for key in dict_map:
                     if dict_map[key] == '':
                          continue
                     dict_map[key] = dict_map[key].value
            except Exception:
                 dict_map = {entry.value: '' for entry in dict_original.values()}
            dict_temp.update(dict_map)
    data_dict['translation'] = {
        en: {'deepl': hand, 'machine': ''}
        for en, hand in dict_temp.items()
    }
            
    with open(f'machine-json/machine-{lang}-{version}.json', 'wt') as f:
        json.dump(data_dict, f)
    
def makePOfromMTjson(MTjsonPath):
    globpattern_original = 'locale/**/en.po'

    with open(MTjsonPath) as f:
        data_dict = json.load(f)
    
    lang = data_dict['lang']
    
    map_dict = {}
    for key, text_dict in data_dict['translation'].items():
        if text_dict['deepl'] != '':
            map_dict[key] = text_dict['deepl']
        elif text_dict['machine'] != '':
            map_dict[key] = text_dict['machine']
            
    for filepath_original in glob_posix(globpattern_original):
        dict_original, _, _ = readpo(filepath_original)
        new_entries = []
        for entry in dict_original.values():
            new_entries.append(StringEntry(entry.key, map_dict.get(entry.value, ''), entry.lineno, False, False))
        writepo(f'locale-machine/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}/{lang}.po', new_entries, f'src-en/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}')

def UpdateMT():
    _MACHINE_FN_PATTERN = re.compile(
    r'^machine-(?P<locale>[a-zA-Z_]+)-(?P<version>v?[0-9\.]+(?:-.*)?)\.json$',
    re.IGNORECASE
    )

    with open('mvloc.config.jsonc') as f:
        config = json5.load(f)

    base_version = config['packaging']['version']

    for pathstr in glob("machine-json/*"):
        path = Path(pathstr).name
        match = _MACHINE_FN_PATTERN.match(path)
        if match is None:
            continue

        match = match.groupdict()
        locale = match['locale']
        version = match['version']
        if version == base_version:
            print(f'locale: {locale} is up-to-date.')
            continue

        print(f'creating machine-{locale}-{base_version}.json')
        makeMTjson(locale, base_version)

        print(f'updating {locale}...')
        with open(pathstr) as f:
            old_json = json.load(f)
        newpath = f'machine-json/machine-{locale}-{base_version}.json'
        with open(newpath) as f:
            new_json = json.load(f)

        for key in new_json['translation'].keys():
            new_json['translation'][key] = old_json['translation'].get(key, {'deepl': '', 'machine': ''})

        with open(newpath, 'wt') as f:
            json.dump(new_json, f)

        Path(pathstr).unlink()

        makePOfromMTjson(newpath)