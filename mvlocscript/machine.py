import json
import json5
from glob import glob
from pathlib import Path
import re
from random import random
from time import sleep
import requests
from mvlocscript.fstools import glob_posix
from mvlocscript.potools import readpo, writepo, StringEntry

#{target_lang: source_lang} use weblate translation for non English source language.
EXCEPTLANG = {'pl': 'ru'}
#Japanese font doesn't include special characters used in MV, so this replaces them with corresponding words.
REPLACE_SPECIAL_CHARACTERS ={
    # 'ja': str.maketrans({
    #     "{":"燃料",  # fuel
    #     "|":"ドローン",  # drones
    #     "}":"ミサイル",  # missiles
    #     "~":"スクラップ",  # scrap
    # })
}

def makeMapDict(lang: str, originalLang: str='en'):
    globpattern_original = f'locale/**/{originalLang}.po'
    
    map_dict = {}
    for filepath_original in glob_posix(globpattern_original):
            dict_original, _, _ = readpo(filepath_original)
            tmp_dict = {}
            try:
                dict_hand, _, _ = readpo(f'locale/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}/{lang}.po')
                for key, entry in dict_original.items():
                     tmp_dict[entry.value] = dict_hand.get(key, '')
                for key in tmp_dict:
                     if tmp_dict[key] == '':
                          continue
                     tmp_dict[key] = tmp_dict[key].value
            except Exception:
                 tmp_dict = {entry.value: '' for entry in dict_original.values()}
            map_dict.update(tmp_dict)
    return map_dict
        
def makeMTjson(lang: str, version: str, originalLang: str='en'):
    data_dict = {}
    data_dict['lang'] = lang
    data_dict['originalLang'] = originalLang
    data_dict['version'] = version
    data_dict['translation'] = {
        en: {'deepl': hand, 'machine': ''}
        for en, hand in makeMapDict(lang, originalLang).items()
    }
    
    path = f'machine-json/machine-{lang}-{version}.json'
    with open(path, 'wt') as f:
        json.dump(data_dict, f)
        
    return path

def getMTjson(lang: str = None, version: str = None):
    _MACHINE_FN_PATTERN = re.compile(
    r'^machine-(?P<locale>[a-zA-Z_]+)-(?P<version>v?[0-9\.]+(?:-.*)?)\.json$',
    re.IGNORECASE
    )
    info_dict = {}
    for pathstr in glob("machine-json/*"):
        match = _MACHINE_FN_PATTERN.match(Path(pathstr).name)
        if match is None:
            continue
        match = match.groupdict()
        info_dict[pathstr] = {'locale': match['locale'], 'version': match['version']}
    if lang is not None:
        info_dict = {key: value for key, value in info_dict.items() if value['locale'] == lang}
    if version is not None:
        info_dict = {key: value for key, value in info_dict.items() if value['version'] == version}
    return [key for key in info_dict.keys()]

def translate(MTjsonPath: str):
    from googletrans import Translator
    
    AUTOSAVE_INTERVAL = 100
    
    with open(MTjsonPath) as f:
        data_dict = json.load(f)
    
    originalLang = data_dict.get('originalLang', 'en')
    target_lang = data_dict['lang']
    source_lang = EXCEPTLANG.get(target_lang, originalLang)
    special_char_transtable_decode = REPLACE_SPECIAL_CHARACTERS.get(target_lang)
    
    all_length = len(data_dict['translation'])
    count = 0
    count_translate = 0
        
    translator = Translator()
    
    def save(data_dict):
        with open(MTjsonPath, 'wt') as f:
            json.dump(data_dict, f)
    
    def _translate(original):
        for i in range(5):
            try:
                translation = translator.translate(original, target_lang, source_lang).text
                return translation, True
            except:
                continue
        return original, False
    
    print(f'translating from {source_lang} to {target_lang}...')
    if source_lang != originalLang:
        map_dict = makeMapDict(source_lang, originalLang)
    for key, text_dict in data_dict['translation'].items():
        count += 1
        if text_dict['machine'] != '' or text_dict['deepl'] != '':
            print(f'{count} done')
            continue
        if source_lang == originalLang:
            target_text = key
        else:
            target_text = map_dict.get(key, '')
        if target_text == '':
            continue
        translated_text, is_success = _translate(target_text)
        if not is_success:
            print(f'translation failed: {translated_text}')
            continue
        translated_text = translated_text.replace('\\ ', '\\')
        if not special_char_transtable_decode is None:
            translated_text = translated_text.translate(special_char_transtable_decode)
        text_dict['machine'] = translated_text
        print(f'{count}/{all_length}\t{translated_text}')
        
        count_translate += 1
        if count_translate % AUTOSAVE_INTERVAL == 0:
            print('auto saving...')
            save(data_dict)

    save(data_dict)

def makePOfromMTjson(MTjsonPath: str):
    with open(MTjsonPath) as f:
        data_dict = json.load(f)
    
    lang = data_dict['lang']
    originalLang = data_dict.get('originalLang', 'en')
    
    globpattern_original = f'locale/**/{originalLang}.po'
    
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
        writepo(f'locale-machine/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}/{lang}.po', new_entries, f'src-{originalLang}/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}')

def TranslateAll():
    for pathstr in getMTjson():
        translate(pathstr)
        makePOfromMTjson(pathstr)
    print('All translation done.')

def updateMT(MTjsonPath: str, new_version: str, force=False):
    with open(MTjsonPath) as f:
        old_json = json.load(f)
    locale = old_json['lang']
    originalLang = old_json.get('originalLang', 'en')
    version = old_json['version']
    if version == new_version and not force:
        print(f'locale: {locale} is up-to-date.')
        return MTjsonPath

    print(f'creating machine-{locale}-{new_version}.json')
    newpath = makeMTjson(locale, new_version, originalLang)

    print(f'updating {locale}...')
    with open(newpath) as f:
        new_json = json.load(f)

    for key in new_json['translation'].keys():
        new_json['translation'][key] = old_json['translation'].get(key, {'deepl': '', 'machine': ''})

    with open(newpath, 'wt') as f:
        json.dump(new_json, f)

    if Path(MTjsonPath).name != Path(newpath).name:
        Path(MTjsonPath).unlink()

    return newpath

def UpdateAllMT(do_translate=False, force=False):
    with open('mvloc.config.jsonc') as f:
        config = json5.load(f)

    base_version = config['packaging']['version']

    for pathstr in getMTjson():
        newpath = updateMT(pathstr, base_version, force)

        if(do_translate):
            translate(newpath)
        
        makePOfromMTjson(newpath)
        
def deepltranslate(api_key: str, MTjsonPath: str, character_limit: int = -1):
    url = "https://api-free.deepl.com/v2/translate"
    #url = "https://api.deepl.com/v2/translate"
    #character_limit = -1 #Limit on number of characters to translate. -1 means unlimited
    retry_number = 5 #Number of retries if translation fails.
    AUTOSAVE_INTERVAL = 50 #Auto save interval for each number of translations.
    DEEPL_LANG_TABLE = {
        'en': 'EN-US',
        'ru': 'RU'
    }
    
    def save(data):
        with open(MTjsonPath, 'wt') as f:
            json.dump(data, f)

    with open(MTjsonPath) as f:
        data = json.load(f)
    
    target_lang = data['lang']
    original_lang = DEEPL_LANG_TABLE.get(data.get('originalLang', 'en'))
    special_char_transtable_decode = REPLACE_SPECIAL_CHARACTERS.get(target_lang)
    
    print(f'deepl translating from {original_lang} to {target_lang}...')
    translation_number = 0
    count_in_total = 0
    for key, text_dict in data['translation'].items():
        if text_dict['deepl'] != '':
            continue
        
        for i in range(retry_number):
            translation_number += len(key)
            if character_limit > -1 and translation_number > character_limit:
                print('Reached character limit which you set.')
                save(data)
                return
            
            params = {
                    'auth_key' : api_key,
                    'text' : key,
                    'target_lang' : target_lang,
                }
            if original_lang:
                params['source_lang': original_lang]
            try:
                response = requests.post(url, data=params)
                status = response.status_code
                
                if status == 200:
                    translated_text = response.json()['translations'][0]['text']
                    translated_text = translated_text.replace('\\ ', '\\')
                    if not special_char_transtable_decode is None:
                        translated_text = translated_text.translate(special_char_transtable_decode)
                    text_dict['deepl'] = translated_text
                    text_dict['machine'] = ''
                    count_in_total += 1
                    print(f'translated {count_in_total} times and {translation_number} characters in total\t{translated_text}')
                    if count_in_total % AUTOSAVE_INTERVAL == 0:
                        print('Auto saving data...')
                        save(data)
                    break
                elif status == 456:
                    print('Reached the translation limit of 500000 characters per month.')
                    save(data)
                    return
                else:
                    print(f'HTTP error : {status}')
                    sleep((2 ** i) + random())
                    continue
                
            except Exception:
                continue
    print('All of the texts have been translated!')
    save(data)
    return

def measureMT(MTjsonPath: str):
    with open(MTjsonPath) as f:
        data = json.load(f)

    all_length = len(data['translation'])
    deepl_length = 0
    deepl_chara_len = 0
    untranslated_len = 0
    untranslated_chara_len = 0

    for key, textdata in data['translation'].items():
        if textdata['deepl'] != '':
            deepl_length += 1
        else:
            deepl_chara_len += len(key)
            if textdata['machine'] == '':
                untranslated_len += 1
                untranslated_chara_len += len(key)
            
    print(f"language: {data['lang']}, version: {data['version']}\n\n*deepl*\nachievement: {deepl_length}/{all_length}({deepl_length / all_length * 100}%)\nleft: {all_length - deepl_length} texts ({deepl_chara_len} characters)\n\n*total*\nachievement: {all_length - untranslated_len}/{all_length}({(all_length -untranslated_len) / all_length * 100}%)\nleft: {untranslated_len} texts ({untranslated_chara_len} characters)\n\n")

def MeasureAllMT():
    for pathstr in getMTjson():
        measureMT(pathstr)