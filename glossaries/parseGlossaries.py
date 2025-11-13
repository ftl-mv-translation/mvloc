from lxml import etree
from glob import glob
from json import dumps

"""
Download glossaries from weblate then put .tbx files into glossaries/src/
Then run this script to convert them into .txt files for use in AI translation.
"""

INSTRUCTIONS = "Here is a glossary mapping terms between two languages. You can use it to improve translation accuracy."

SRC_DIR = "glossaries/src/"
DIST_DIR = "mvlocscript/aitranslation/glossaries/"

def main():
    for filepath in glob(SRC_DIR + "*.tbx"):
        tree = etree.parse(filepath)
        root = tree.getroot()
        entryList = root.xpath("text/body/termEntry")
        print(f"Processing {filepath} with {len(entryList)} entries.")
        
        languages = (None, None)
        result = []
        for entry in entryList:
            langSetList = entry.xpath("langSet")
            assert len(langSetList) == 2, "Expected exactly two langSet elements"
            if languages == (None, None):
                languages = (langSetList[0].get("{http://www.w3.org/XML/1998/namespace}lang"), langSetList[1].get("{http://www.w3.org/XML/1998/namespace}lang"))
                print(f"Detected languages: {languages[0]} and {languages[1]}")
            elif languages != (langSetList[0].get("{http://www.w3.org/XML/1998/namespace}lang"), langSetList[1].get("{http://www.w3.org/XML/1998/namespace}lang")):
                raise ValueError("Inconsistent language pairs detected.")
            
            term_orig = langSetList[0].xpath("tig/term")[0].text.strip()
            term_trans = langSetList[1].xpath("tig/term")[0].text
            assert term_orig not in result, f"Duplicate term found: {term_orig}"
            assert term_orig, "Original term is empty."
            if not term_trans:
                term_trans = term_orig
            note =entry.xpath("note")[0].text if entry.xpath("note") else None
            if note:
                result.append({languages[0]: term_orig, languages[1]: term_trans, "note": note})
            else:
                result.append({languages[0]: term_orig, languages[1]: term_trans})

        with open(f"{DIST_DIR}{languages[0]}-{languages[1]}.txt", "w", encoding="utf-8") as f:
            f.write(INSTRUCTIONS + "\n" + dumps(result, ensure_ascii=False))
        
        print(f"Saved glossary to {DIST_DIR}{languages[0]}-{languages[1]}.txt")

if __name__ == "__main__":
    main()