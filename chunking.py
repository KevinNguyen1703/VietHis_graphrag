import re
from typing import List, Dict


def chunking_by_markers(
        tokens_list: List[List[int]],  # Tokenized document
        doc_keys: List[str],  # Document keys (ids or titles)
        tiktoken_model,  # The tiktoken model for encoding/decoding
        overlap_token_size=128,  # Overlap token size for chunks
        max_token_size=2048,  # Maximum token size per chunk
) -> List[Dict]:
    # Define the pattern for matching the section markers like "I.", "II.", "III."
    marker_pattern = re.compile(r"([IVXLCDM]+[.])\s*(.*?)(?=(\n[IVXLCDM]+[.])|\Z)", re.DOTALL)

    results = []

    for index, tokens in enumerate(tokens_list):
        # Reconstruct the document from tokens (or use it as is if it's text)
        doc_text = tiktoken_model.decode(tokens)

        # Split the document into chunks based on the markers
        chunks = []
        for match in marker_pattern.finditer(doc_text):
            chunk_title = match.group(1).strip()  # The "I.", "II.", etc.
            chunk_content = match.group(2).strip()  # The content after the marker

            # Combine marker with content to form a chunk
            chunks.append(f"{chunk_title} {chunk_content}")

        # Now process the chunks for tokenization
        for i, chunk in enumerate(chunks):
            # Tokenize the chunk
            chunk_tokens = tiktoken_model.encode(chunk)
            chunk_length = len(chunk_tokens)

            # Check if the chunk exceeds max token size and split if necessary
            if chunk_length > max_token_size:
                # Split the chunk further if necessary
                start = 0
                while start < chunk_length:
                    end = min(start + max_token_size, chunk_length)
                    chunk_part = chunk_tokens[start:end]
                    start = end
                    results.append({
                        "tokens": len(chunk_part),
                        "content": tiktoken_model.decode(chunk_part).strip(),
                        "chunk_order_index": i,
                        "full_doc_id": doc_keys[index],
                    })
            else:
                results.append({
                    "tokens": chunk_length,
                    "content": chunk.strip(),
                    "chunk_order_index": i,
                    "full_doc_id": doc_keys[index],
                })

    return results
