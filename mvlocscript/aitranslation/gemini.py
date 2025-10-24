#!/usr/bin/env python3
"""
Features:
- Translate each value in the input JSON file to Japanese
- Use Google Gen AI (Gemini) API for batch translation (batch_size entries per batch)
- Strictly validate keys and order after each translation (with periodic cumulative validation during translation)
- Output final JSON (preserving original key order)
- Dynamic batch sizing based on token limits

Dependencies:
pip install google-genai

Environment variables:
GEMINI_API_KEY should be set to your API Key

Usage example:
python aitranslation.py input.json
"""

import json
import os
import time
import math
from collections import OrderedDict
from typing import List
from difflib import SequenceMatcher
from google import genai
from google.genai import types


# ---- Configuration ----
current_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
API_KEY = os.environ.get("GEMINI_API_KEY", None)  # Recommended to set via environment variable
BATCH_SIZE = 600          # Initial batch size
MAX_RETRIES = 10          # Maximum retry attempts when a single batch fails
RETRY_DELAY = 2           # Retry wait time in seconds

MAX_INPUT_OUTPUT_TOKENS_RATIO = 0.48  # Max input tokens as a ratio of max output tokens for the model
DYNAMIC_BATCH_SIZING = True  # If true, dynamically adjust batch size based on input token limit

input_token_limit = None
output_token_limit = None

MODEL_IDS = {
    "gemini-2.5-pro": 10,
    "gemini-2.5-flash": 9,
}

def set_model(model_name: str):
    if model_name not in MODEL_IDS:
        raise ValueError(f"Unknown model name: {model_name}. Available models: {list(MODEL_IDS.keys())}")
    global current_model
    current_model = model_name

def get_model_id():
    id = MODEL_IDS.get(current_model, None)
    if id is None:
        raise ValueError(f"Unknown model name: {current_model}")
    return id

# ---- Helper Functions ----
def load_json_ordered(path: str) -> OrderedDict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=OrderedDict)

def save_json_ordered(obj: OrderedDict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def extract_json_from_text(t: str):
    """Try to extract the first JSON object from the model's returned text (from first { to last })."""
    t = t.strip().replace('\\": "', '\\"": "')
    if t.find("{") != 0:
        raise ValueError("Response does not start with '{'")
    
    end = t.rfind("}")
    if end != len(t) - 1:
        last_entry_pos = t.rfind("\",\n  ")
        valid_json = t[:last_entry_pos + 1] + "\n}"
        return json.loads(valid_json, object_pairs_hook=OrderedDict)
    return json.loads(t, object_pairs_hook=OrderedDict)

def two_text_is_enoughly_equal(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() > 0.95

# ---- Create client ----
def make_client():
    # Two initialization methods: use genai.Client(api_key=...) to explicitly pass key; otherwise rely on environment variable
    try:
        if API_KEY:
            client = genai.Client(api_key=API_KEY)
        else:
            client = genai.Client()  # Will try to read GEMINI_API_KEY from environment variable
        return client
    except Exception as e:
        raise RuntimeError("Unable to create GenAI client, please confirm package and API KEY configuration are correct.") from e

# ---- Dynamic batch sizing ----
def calculate_optimal_batch_size(client, model: str, remaining_pairs: List[tuple]) -> int:
    """
    Calculate optimal batch size by iteratively adjusting based on token count.
    
    Args:
        client: GenAI client
        model: Model name
        remaining_pairs: Remaining pairs to test with
    
    Returns:
        Optimal batch size that stays near MAX_INPUT_TOKENS
    """
    if not DYNAMIC_BATCH_SIZING or not remaining_pairs:
        return min(BATCH_SIZE, len(remaining_pairs))
    
    assert output_token_limit is not None, "Output token limit must be known for dynamic batch sizing."
    
    current_batch_size = min(BATCH_SIZE, len(remaining_pairs))
    
    print(f"[INFO] Calculating optimal batch size for {len(remaining_pairs)} remaining items, starting from {current_batch_size}...")
    
    count = 0
    while current_batch_size > 0:
        count += 1
        if count > 50:
            raise RuntimeError("Failed to determine optimal batch size after 50 iterations.")
        # Test current batch size
        test_pairs = remaining_pairs[:current_batch_size]
        test_prompt = build_prompt_for_batch(test_pairs)
        
        try:
            token_count_response = client.models.count_tokens(
                model=model,
                contents=test_prompt
            )
            token_count = token_count_response.total_tokens
            # print(f"[DEBUG] Batch size {current_batch_size}: {token_count} tokens")
            
            if token_count > output_token_limit * MAX_INPUT_OUTPUT_TOKENS_RATIO:
                # Too many tokens, decrease batch size
                current_batch_size = max(1, int(current_batch_size * 0.9))
            elif token_count < output_token_limit * MAX_INPUT_OUTPUT_TOKENS_RATIO * 0.9:  # If we're using less than 90% of limit
                # Try to increase batch size
                new_batch_size = min(len(remaining_pairs), int(current_batch_size * 1.1))
                if new_batch_size == current_batch_size:
                    # Can't increase further, we've found optimal size
                    break
                current_batch_size = new_batch_size
            else:
                # We're in the sweet spot (90-100% of MAX_INPUT_TOKENS)
                break
                
        except Exception as e:
            print(f"[WARN] Error counting tokens for batch size {current_batch_size}: {e}")
            current_batch_size = max(1, int(current_batch_size * 0.9))
    
    print(f"[INFO] Optimal batch size determined: {current_batch_size}")
    return current_batch_size

# ---- Generate prompt ----
def build_prompt_for_batch(pairs: List[tuple]) -> str:
    """
    pairs: list of (key, value)
    Require model to output a JSON object: { "key1": "Japanese text", ... }
    Strictly require only JSON output (or try to output only JSON)
    """
    sample = OrderedDict(pairs)
    return json.dumps(sample, ensure_ascii=False, indent=2)


def build_config_for_batch(lang: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=(
            "You are a professional translator. "
            f"Translate the following JSON object's values into the language whose lang code is {lang}. "
            "All terms are from the game FTL: Faster Than Light, so translate them in the context of FTL: Faster Than Light. "
            "RETURN ONLY a valid JSON object mapping the exact same keys to the translated strings. "
            "Do not add extra commentary. Maintain the same key order."
        ),
        response_mime_type="application/json"
    )

# ---- Translate one batch ----
def translate_batch(client, model: str, batch_pairs: List[tuple], lang: str) -> OrderedDict:
    config = build_config_for_batch(lang)
    prompt = build_prompt_for_batch(batch_pairs)
    for attempt in range(1, MAX_RETRIES + 1):
        text = None
        try:
            # Use simple interface: client.models.generate_content
            resp = client.models.generate_content(
                model=model,
                config=config,
                contents=prompt,
            )
            # Different SDK versions may have different return value objects, mainly get text
            text = getattr(resp, "text", None)
            if text is None:
                # Try str(resp)
                text = str(resp)
            # Extract JSON
            out = extract_json_from_text(text)
            # Validate keys
            out_keys = list(out.keys())
            orig_keys = [k for k, _ in batch_pairs]
            if len(out_keys) < len(orig_keys):
                orig_keys = orig_keys[:len(out_keys)]  # Allow for some missing keys, but not extra keys
            assert len(out_keys) == len(orig_keys), f"Returned keys count {len(out_keys)} doesn't match input {len(orig_keys)}"
            if out_keys != orig_keys:
                mismatched = [(o, i) for o, i in zip(out_keys, orig_keys) if o != i]
                if all(two_text_is_enoughly_equal(o, i) for o, i in mismatched):
                    # print(f"[WARN] Minor key mismatches detected but considered 'enoughly equal': {mismatched}")
                    out_values = list(out.values())
                    out = OrderedDict()
                    for i, k in enumerate(orig_keys):
                        out[k] = out_values[i]
                else:
                    # If order or keys don't match, consider this return invalid, throw exception to trigger retry
                    with open("last_invalid_response.log", "w", encoding="utf-8") as f:
                        f.write(text)
                    raise ValueError(f"Returned keys don't match input.\nMismatched keys: {mismatched}")
            
            # Log token usage if available
            metadata = getattr(resp, "usage_metadata", None)
            if metadata:
                try:
                    input_tokens = metadata.prompt_token_count
                    output_tokens = metadata.candidates_token_count
                    print(f"[INFO] Tokens used - input: {input_tokens}/{input_token_limit} ({math.ceil(input_tokens/input_token_limit*100) if input_token_limit else 'N/A'}%), output: {output_tokens}/{output_token_limit} ({math.ceil(output_tokens/output_token_limit*100) if output_token_limit else 'N/A'}%)")
                    with open("token_usage_ratio.log", "a", encoding="utf-8") as logf:
                        logf.write(f"{input_tokens},{output_tokens},{input_tokens/output_tokens if output_tokens else 'N/A'}\n")
                except Exception:
                    pass
            # OK, return OrderedDict
            return OrderedDict(out)
        except Exception as e:
            print(f"[WARN] Batch translation attempt {attempt} failed: {e}")
            if text:
                with open("last_invalid_response.log", "w", encoding="utf-8") as f:
                    f.write(text)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            else:
                raise
    # unreachable
    raise RuntimeError("Reached maximum retries and still failed")

# ---- Main Process ----
def translate_file(infile: str,
                   outfile: str,
                   lang: str,
                   batch_size: int = BATCH_SIZE):
    # load
    data_full = load_json_ordered(infile)
    if len(data_full) == 0:
        print(f"No entries found in {infile}, exiting.")
        return
    data = {k: v for k, v in data_full.items() if not v}  # Only translate entries with empty values
    keys = list(data.keys())
    total = len(keys)
    print(f"Loading {infile}: total {total} entries. initial batch_size={batch_size}")

    client = make_client()
    MODEL_INFO = client.models.get(model=current_model)
    global input_token_limit, output_token_limit
    input_token_limit = MODEL_INFO.input_token_limit
    output_token_limit = MODEL_INFO.output_token_limit
    print(f"Using model: {current_model}, input token limit: {MODEL_INFO.input_token_limit}, output token limit: {MODEL_INFO.output_token_limit}")

    translated = OrderedDict()
    processed = 0
    batch_idx = 0
    remaining_keys = keys.copy()

    # Process batches with dynamic sizing
    while remaining_keys:
        batch_idx += 1
        
        # Create remaining pairs for batch size calculation
        remaining_pairs = [(k, data[k]) for k in remaining_keys]
        
        # Calculate optimal batch size for current remaining items
        optimal_batch_size = calculate_optimal_batch_size(client, current_model, remaining_pairs)
        
        # Take the batch
        current_batch_keys = remaining_keys[:optimal_batch_size]
        
        batch_pairs = [(k, data[k]) for k in current_batch_keys]
        print(f"\n[INFO] Translating batch {batch_idx}: {len(batch_pairs)} entries ({processed+1} - {processed+len(batch_pairs)})...")
        out_pairs = translate_batch(client, current_model, batch_pairs, lang)
        
        output_batch_size = len(out_pairs)
        print(f"[INFO] Translated {output_batch_size} entries. Initial batch size was {optimal_batch_size}. Missing {optimal_batch_size - output_batch_size} entries.")
        remaining_keys = remaining_keys[output_batch_size:]
        
        # append results preserving order
        for k in out_pairs.keys():
            translated[k] = out_pairs[k]
        processed += output_batch_size

        # Periodic validation: confirm current cumulative translated keys match original order
        cur_keys = list(translated.keys())
        orig_prefix = keys[:len(cur_keys)]
        if cur_keys != orig_prefix:
            raise RuntimeError(f"Cumulative validation failed: translated keys order doesn't match original at {processed}")
        print(f"[OK] Cumulative validation passed (translated {processed}/{total} entries)")
        data_full.update(translated)
        save_json_ordered(data_full, outfile)

        time.sleep(0.2)  # Small interval to prevent too fast requests (can be adjusted/removed as needed)

    # Final save
    data_full.update(translated)
    save_json_ordered(data_full, outfile)
    print(f"\nCompleted! Saved to: {outfile} (total {len(data_full)} entries)")

if __name__ == "__main__":
    infile = "out.json"
    outfile = "out.json"
    translate_file(infile, outfile)
