import json
import json5
from glob import glob
from pathlib import Path
import re
from random import random
from time import sleep
import requests
from collections import defaultdict
from mvlocscript.fstools import glob_posix, ensureparent
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
MT_REPLACE_MAPS ={
    'ja': {
        '多元宇宙': 'マルチバース',
        'マルチヴァース': 'マルチバース',
        'レネゲード': 'レネゲイド',
        '無料カマキリ': 'フリー・マンティス',
        '無料マンティス': 'フリー・マンティス',
        '無料のカマキリ': 'フリー・マンティス',
        '無料のマンティス': 'フリー・マンティス',
        '無料 マンティス': 'フリー・マンティス',
        '無料 カマキリ': 'フリー・マンティス',
        'ナメクジ': 'スラッグ',
        'カマキリ': 'マンティス',
        '蘭': 'オーキッド',

    },
    'fr': {
        '«': '"',
        '»': '"',
        '—': '-',
        'ʼ': '\'',

    }
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
        
def makeMTjson(lang: str, version: str, originalLang: str='en', tmpName: bool=False):
    data_dict = {}
    data_dict['lang'] = lang
    data_dict['originalLang'] = originalLang
    data_dict['version'] = version
    data_dict['translation'] = {
        en: {'advanced': {}, 'deepl': '', 'machine': '', 'done': hand != ''}
        for en, hand in makeMapDict(lang, originalLang).items()
    }
    
    tmpEscape = '_' if tmpName else ''
    path = f'machine-json/{tmpEscape}machine-{lang}-{version}.json'
    ensureparent(path)
    with open(path, 'wt', encoding='utf8') as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=2)
        
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

def translate(MTjsonPath: str, model = None, force: bool = False):
    from mvlocscript.aitranslation import gemini
    
    if model is not None:
        gemini.set_model(model)
    
    with open(MTjsonPath, encoding='utf8') as f:
        data_dict = json.load(f)
    
    target_lang = data_dict['lang']
    
    queryFilePath = Path(f"machine-json/tmp_query/{target_lang}-{gemini.get_model_id()}.json")
    if not queryFilePath.exists():
        ensureparent(queryFilePath)
        out = {}
        for key, text_dict in data_dict['translation'].items():
            if text_dict['done']:
                continue
            
            if not force and (text_dict['advanced'] != {} and max([int(i) for i in text_dict['advanced'].keys()]) >= gemini.get_model_id()):
                continue
            
            out[key] = ''
        
        if out == {}:
            print('all texts are already translated!')
            return
        with open(queryFilePath, 'wt', encoding='utf8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    gemini.translate_file(str(queryFilePath), str(queryFilePath), target_lang, data_dict["originalLang"])
    
    with open(queryFilePath, encoding='utf8') as f:
        result_dict = json.load(f)
    
    for key, translated_text in result_dict.items():
        data_dict['translation'][key]['advanced'][str(gemini.get_model_id())] = {'model': gemini.current_model, 'text': translated_text}

    with open(MTjsonPath, 'wt', encoding='utf8') as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=2)
    
    print('translation done. cleaning up temporary files...')
    queryFilePath.unlink()

def _translate_old(MTjsonPath: str):
    "DEPRECATED"
    from googletrans import Translator
    
    AUTOSAVE_INTERVAL = 100
    
    with open(MTjsonPath, encoding='utf8') as f:
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
        with open(MTjsonPath, 'wt', encoding='utf8') as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)
    
    def _translate(original):
        for i in range(5):
            try:
                translation = translator.translate(original, target_lang, source_lang).text
                return translation, True
            except:
                continue
        return original, False
    
    def try_line_by_line_translate(original: str):
        line_list = original.split('\n')
        ret_list = []
        for line in line_list:
            split_list = re.split('\S', line)
            left_space = split_list[0]
            right_space = split_list[-1]
            translated_text, is_success = _translate(line.strip())
            if not is_success:
                return original, False

            ret_list.append(left_space + translated_text + right_space)
        return '\n'.join(ret_list), True
    
    print(f'translating from {source_lang} to {target_lang}...')
    if source_lang != originalLang:
        map_dict = makeMapDict(source_lang, originalLang)
    for key, text_dict in data_dict['translation'].items():
        count += 1
        if text_dict['done'] or text_dict['machine'] != '' or text_dict['deepl'] != '' or text_dict['advanced'] != {}:
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
            translated_text, is_success = try_line_by_line_translate(target_text)
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
    def replace_from_map(text, replace_map):
        if replace_map is None or not text:
            return text
        
        for before, after in replace_map.items():
            text = text.replace(before, after)
        return text
    with open(MTjsonPath, encoding='utf8') as f:
        data_dict = json.load(f)
    
    lang = data_dict['lang']
    originalLang = data_dict.get('originalLang', 'en')
    
    globpattern_original = f'locale/**/{originalLang}.po'
    
    map_dict = {}
    for key, text_dict in data_dict['translation'].items():
        if text_dict['advanced'] != {}:
            list_priorities = [int(i) for i in text_dict['advanced'].keys()]
            map_dict[key] = text_dict['advanced'][str(max(list_priorities))]['text']
        elif text_dict['deepl'] != '':
            map_dict[key] = text_dict['deepl']
        elif text_dict['machine'] != '':
            map_dict[key] = text_dict['machine']
    
    replace_map = MT_REPLACE_MAPS.get(lang)
            
    for filepath_original in glob_posix(globpattern_original):
        dict_original, _, _ = readpo(filepath_original)
        new_entries = []
        for entry in dict_original.values():
            new_entries.append(StringEntry(entry.key, replace_from_map(map_dict.get(entry.value, ''), replace_map), entry.lineno, False, False))
        target_path = f'locale-machine/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}/{lang}.po'
        ensureparent(target_path)
        writepo(target_path, new_entries, f'src-{originalLang}/{Path(filepath_original).parent.parent.name}/{Path(filepath_original).parent.name}')

def TranslateAll():
    for pathstr in getMTjson():
        translate(pathstr)
        makePOfromMTjson(pathstr)
    print('All translation done.')

def updateMT(MTjsonPath: str, new_version: str, force=False):
    with open(MTjsonPath, encoding='utf8') as f:
        old_json = json.load(f)
    locale = old_json['lang']
    originalLang = old_json.get('originalLang', 'en')

    print(f'creating machine-{locale}-{new_version}.json')
    newpath = makeMTjson(locale, new_version, originalLang, True)

    print(f'updating {locale}...')
    with open(newpath, encoding='utf8') as f:
        new_json = json.load(f)

    for key in new_json['translation'].keys():
        old = old_json['translation'].get(key, None)
        if old is not None:
            new_json['translation'][key]['advanced'] = old.get('advanced', {})
            new_json['translation'][key]['deepl'] = old['deepl']
            new_json['translation'][key]['machine'] = old['machine']
            new_json['translation'][key]['done'] = new_json['translation'][key]['done'] or old.get('done', False)

    with open(newpath, 'wt', encoding='utf8') as f:
        json.dump(new_json, f, ensure_ascii=False, indent=2)

    newpath_Path = Path(newpath)
    oldpath_Path = Path(MTjsonPath)
    if oldpath_Path.name != newpath_Path.name:
        oldpath_Path.unlink()
    
    newpath_Path = newpath_Path.rename(newpath_Path.with_name(newpath_Path.name[1:]))

    return f'machine-json/{newpath_Path.name}'

def UpdateAllMT(do_translate=False, force=False):
    with open('mvloc.config.jsonc', encoding='utf8') as f:
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
        'ru': 'RU',
        'pt_BR': 'PT-BR',
    }
    
    def save(data):
        with open(MTjsonPath, 'wt', encoding='utf8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    with open(MTjsonPath, encoding='utf8') as f:
        data = json.load(f)
    
    target_lang = DEEPL_LANG_TABLE.get(data['lang'], data['lang'])
    original_lang = DEEPL_LANG_TABLE.get(data.get('originalLang', 'en'))
    special_char_transtable_decode = REPLACE_SPECIAL_CHARACTERS.get(target_lang)
    
    print(f'deepl translating from {original_lang} to {target_lang}...')
    translation_number = 0
    count_in_total = 0
    for key, text_dict in data['translation'].items():
        if text_dict['done'] or text_dict['deepl'] != '':
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
            # if original_lang:
            #     params['source_lang'] = original_lang
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
    with open(MTjsonPath, encoding='utf8') as f:
        data = json.load(f)

    all_count = len(data['translation'])
    hand_count = 0
    deepl_count = 0
    googletrans_count = 0
    untranslated_count = 0
    untranslated_chara_len = 0
    advanced_counts = defaultdict(int)
    advanced_names = {}

    for key, textdata in data['translation'].items():
        if textdata['done']:
            hand_count += 1
        elif textdata['advanced'] != {}:
            list_priorities = [int(i) for i in textdata['advanced'].keys()]
            max_priority = max(list_priorities)
            advanced_counts[max_priority] += 1
            if not max_priority in advanced_names:
                advanced_names[max_priority] = textdata['advanced'][str(max_priority)]['model']
        elif textdata['deepl'] != '':
            deepl_count += 1
        elif textdata['machine'] != '':
            googletrans_count += 1
        else:
            untranslated_count += 1
            untranslated_chara_len += len(key)

    advanced_string = '\n'.join([f"{advanced_names[priority]}: {count / all_count * 100:.2f}% ({count}/{all_count})" for priority, count in sorted(advanced_counts.items(), reverse=True)])
    if advanced_string != '':
        advanced_string += '\n'

    print(f"language: {data['lang']}, version: {data['version']}\n\n"
          "*overall achievement*\n"
          f"achievement: {(all_count - untranslated_count) / all_count * 100:.2f}% ({all_count - untranslated_count}/{all_count})\n"
          f"left: {untranslated_count} texts ({untranslated_chara_len} characters)\n\n"
          "*translation methods composition (in order of high to low quality in general)*\n"
          f"hand: {hand_count / all_count * 100:.2f}% ({hand_count}/{all_count})\n"
          f"{advanced_string}"
          f"deepl: {deepl_count / all_count * 100:.2f}% ({deepl_count}/{all_count})\n"
          f"googletrans: {googletrans_count / all_count * 100:.2f}% ({googletrans_count}/{all_count})\n")

def MeasureAllMT():
    for pathstr in getMTjson():
        print("\n")
        measureMT(pathstr)