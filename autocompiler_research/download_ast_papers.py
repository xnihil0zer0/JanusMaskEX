import urllib.request
import time
import os

papers = {
    "recoder.pdf": "https://arxiv.org/pdf/2106.08253.pdf",
    "mulpor.pdf": "https://shangwenwang.github.io/files/ISSTA-24.pdf"
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

dest_dir = "/home/xnihil0zer0/JanusMaskJR/autocompiler_research"
os.makedirs(dest_dir, exist_ok=True)

for filename, url in papers.items():
    dest_path = os.path.join(dest_dir, filename)
    print(f"Downloading {filename} from {url} to {dest_path}...")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            with open(dest_path, 'wb') as out_file:
                out_file.write(response.read())
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")
    time.sleep(2) # Sleep for 2 seconds to be polite
