import urllib.request
import time
import os

# Define the papers to download
papers = {
    "type_level_property_based_testing.pdf": "https://arxiv.org/pdf/2407.12726.pdf",
    "differential_fuzzing_functional_equivalence.pdf": "https://arxiv.org/pdf/2602.15761.pdf"
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

output_dir = "/home/xnihil0zer0/JanusMaskJR/autocompiler_research"
os.makedirs(output_dir, exist_ok=True)

for filename, url in papers.items():
    dest_path = os.path.join(output_dir, filename)
    print(f"Downloading {filename} from {url} to {dest_path}...")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            with open(dest_path, 'wb') as out_file:
                out_file.write(response.read())
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")
    time.sleep(2) # Polite delay
